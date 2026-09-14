from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_quiz_service
from app.api.schemas.documents import ErrorResponse
from app.api.schemas.quizzes import (
    AttemptCreateRequest,
    AttemptResponse,
    QuizCreateRequest,
    QuizResponse,
)
from app.chat.models import (
    ChatAuthenticationError,
    ChatConfigurationError,
    ChatInvalidRequestError,
    ChatOutputInvalidError,
    ChatQuotaError,
    ChatSafetyBlockedError,
    ChatTimeoutError,
    ChatTruncatedError,
    ChatUnavailableError,
)
from app.embeddings.models import (
    EmbeddingAuthenticationError,
    EmbeddingConfigurationError,
    EmbeddingInvalidRequestError,
    EmbeddingQuotaError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
    EmbeddingValidationError,
)
from app.progress.models import TopicInputError, TopicNotFound
from app.quiz.models import (
    AttemptInputError,
    AttemptNotFound,
    IdempotencyConflict,
    QuizInputError,
    QuizInsufficientContext,
    QuizNotFound,
    QuizOutputInvalid,
    SubmittedAnswer,
)
from app.quiz.service import QuizService
from app.retrieval.service import SearchInputError

router = APIRouter(tags=["quizzes"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _documented_error(description: str, code: str, message: str) -> dict[str, object]:
    return {
        "model": ErrorResponse,
        "description": description,
        "content": {
            "application/json": {"example": {"detail": {"code": code, "message": message}}}
        },
    }


_ERROR_RESPONSES = {
    404: _documented_error("Quiz or attempt does not exist.", "quiz_not_found", "Not found"),
    409: _documented_error(
        "Idempotency key payload conflict.",
        "idempotency_conflict",
        "The key was already used with another payload",
    ),
    422: _documented_error(
        "Input or source context is insufficient.",
        "quiz_insufficient_context",
        "No eligible source context is available",
    ),
    429: _documented_error(
        "Provider quota is exhausted.", "chat_quota_exceeded", "Provider quota is exhausted"
    ),
    502: _documented_error(
        "Provider returned an invalid quiz.",
        "quiz_output_invalid",
        "The provider returned an invalid quiz",
    ),
    503: _documented_error(
        "Database or provider is unavailable.",
        "database_unavailable",
        "Quiz storage is unavailable",
    ),
}


@router.post(
    "/quizzes",
    response_model=QuizResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and persist one grounded single-choice quiz",
    responses=_ERROR_RESPONSES,
)
def create_quiz(
    request: QuizCreateRequest,
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizResponse:
    try:
        result = service.create_quiz(
            topic_id=request.topic_id,
            topic=request.topic,
            document_ids=request.document_ids,
            question_count=request.question_count,
        )
    except (QuizInputError, TopicInputError, SearchInputError, QuizInsufficientContext) as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except TopicNotFound as exc:
        raise _error(404, exc.code, "Topic was not found") from exc
    except (QuizOutputInvalid, ChatOutputInvalidError, ChatTruncatedError) as exc:
        raise _error(502, exc.code, "The provider returned an invalid quiz") from exc
    except ChatSafetyBlockedError as exc:
        raise _error(422, exc.code, "Quiz generation was blocked for safety") from exc
    except (ChatQuotaError, EmbeddingQuotaError) as exc:
        raise _error(429, exc.code, "Provider quota is currently exhausted") from exc
    except (ChatInvalidRequestError, EmbeddingInvalidRequestError, EmbeddingValidationError) as exc:
        raise _error(502, exc.code, "Provider rejected or returned an invalid result") from exc
    except (
        ChatAuthenticationError,
        ChatConfigurationError,
        ChatTimeoutError,
        ChatUnavailableError,
        EmbeddingAuthenticationError,
        EmbeddingConfigurationError,
        EmbeddingTimeoutError,
        EmbeddingUnavailableError,
    ) as exc:
        raise _error(503, exc.code, "The provider is temporarily unavailable") from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Quiz storage is unavailable") from exc
    return QuizResponse(**asdict(result))


@router.get(
    "/quizzes/{quiz_id}",
    response_model=QuizResponse,
    summary="Read a quiz without answer keys or explanations",
    responses={404: _ERROR_RESPONSES[404], 503: _ERROR_RESPONSES[503]},
)
def get_quiz(
    quiz_id: Annotated[int, Path(gt=0)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizResponse:
    try:
        result = service.get_quiz(quiz_id)
    except QuizNotFound as exc:
        raise _error(404, exc.code, "Quiz was not found") from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Quiz storage is unavailable") from exc
    return QuizResponse(**asdict(result))


@router.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=AttemptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Score one complete quiz attempt using the persisted server-side key",
    responses=_ERROR_RESPONSES,
)
def submit_attempt(
    quiz_id: Annotated[int, Path(gt=0)],
    request: AttemptCreateRequest,
    response: Response,
    service: Annotated[QuizService, Depends(get_quiz_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)],
) -> AttemptResponse:
    try:
        result = service.submit_attempt(
            quiz_id=quiz_id,
            idempotency_key=idempotency_key,
            answers=[SubmittedAnswer(**answer.model_dump()) for answer in request.answers],
        )
    except QuizNotFound as exc:
        raise _error(404, exc.code, "Quiz was not found") from exc
    except AttemptInputError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except IdempotencyConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Quiz storage is unavailable") from exc
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return AttemptResponse(**asdict(result))


@router.get(
    "/quiz-attempts/{attempt_id}",
    response_model=AttemptResponse,
    summary="Read a submitted attempt with answer key, explanation, and sources",
    responses={404: _ERROR_RESPONSES[404], 503: _ERROR_RESPONSES[503]},
)
def get_attempt(
    attempt_id: Annotated[int, Path(gt=0)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> AttemptResponse:
    try:
        result = service.get_attempt(attempt_id)
    except AttemptNotFound as exc:
        raise _error(404, exc.code, "Quiz attempt was not found") from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Quiz storage is unavailable") from exc
    return AttemptResponse(**asdict(result))
