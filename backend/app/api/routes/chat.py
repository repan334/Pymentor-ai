from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_rag_tutor_service
from app.api.schemas.chat import ChatRequest, ChatResponse, CitationResponse
from app.api.schemas.documents import ErrorResponse
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
from app.rag.service import RagInputError, RagTutorService
from app.retrieval.service import SearchInputError

router = APIRouter(tags=["tutor"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


_RESPONSES = {
    422: {
        "model": ErrorResponse,
        "description": "Input is invalid or generation was blocked for safety.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "chat_safety_blocked",
                        "message": "The tutor response was blocked for safety",
                    }
                }
            }
        },
    },
    429: {
        "model": ErrorResponse,
        "description": "Gemini quota is exhausted after bounded retries.",
    },
    502: {
        "model": ErrorResponse,
        "description": "Provider output is malformed, truncated, or has invalid citations.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "chat_output_invalid",
                        "message": "The tutor provider returned an invalid response",
                    }
                }
            }
        },
    },
    503: {
        "model": ErrorResponse,
        "description": "Database, embedding, or chat provider is unavailable.",
    },
}


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Answer one standalone Python question from eligible document chunks",
    responses=_RESPONSES,
)
def chat(
    request: ChatRequest,
    service: Annotated[RagTutorService, Depends(get_rag_tutor_service)],
) -> ChatResponse:
    try:
        result = service.answer(
            question=request.question,
            top_k=request.top_k,
            document_ids=request.document_ids,
        )
    except (RagInputError, SearchInputError) as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except ChatSafetyBlockedError as exc:
        raise _error(422, exc.code, "The tutor response was blocked for safety") from exc
    except ChatQuotaError as exc:
        raise _error(429, exc.code, "Chat quota is currently exhausted") from exc
    except (ChatOutputInvalidError, ChatTruncatedError, ChatInvalidRequestError) as exc:
        raise _error(502, exc.code, "The tutor provider returned an invalid response") from exc
    except (
        ChatAuthenticationError,
        ChatConfigurationError,
        ChatTimeoutError,
        ChatUnavailableError,
    ) as exc:
        raise _error(503, exc.code, "The tutor provider is temporarily unavailable") from exc
    except EmbeddingQuotaError as exc:
        raise _error(429, exc.code, "Embedding quota is currently exhausted") from exc
    except (
        EmbeddingInvalidRequestError,
        EmbeddingValidationError,
    ) as exc:
        raise _error(502, exc.code, "The embedding provider returned an invalid response") from exc
    except (
        EmbeddingAuthenticationError,
        EmbeddingConfigurationError,
        EmbeddingTimeoutError,
        EmbeddingUnavailableError,
    ) as exc:
        raise _error(503, exc.code, "The embedding provider is temporarily unavailable") from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Document storage is unavailable") from exc

    return ChatResponse(
        status=result.status,
        answer=result.answer,
        citations=[CitationResponse(**asdict(citation)) for citation in result.citations],
    )
