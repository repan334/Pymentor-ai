from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_progress_service
from app.api.schemas.documents import ErrorResponse
from app.api.schemas.progress import (
    QuizTopicAssignmentRequest,
    QuizTopicAssignmentResponse,
    TopicCreateRequest,
    TopicListResponse,
    TopicProgressResponse,
    TopicResponse,
)
from app.progress.models import (
    QuizTopicNotFound,
    TopicConflict,
    TopicInputError,
    TopicNotFound,
)
from app.progress.service import ProgressService

router = APIRouter(tags=["topics and progress"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Topic or quiz does not exist."},
    409: {"model": ErrorResponse, "description": "Topic identity conflicts."},
    422: {"model": ErrorResponse, "description": "Input validation failed."},
    503: {"model": ErrorResponse, "description": "Database is unavailable."},
}


@router.post(
    "/topics",
    response_model=TopicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a stable topic and assign exact-name legacy quizzes",
    responses={409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]},
)
def create_topic(
    request: TopicCreateRequest,
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> TopicResponse:
    try:
        result = service.create_topic(
            topic_id=request.id,
            display_name=request.display_name,
            description=request.description,
        )
    except TopicInputError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except TopicConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Topic storage is unavailable") from exc
    return TopicResponse(**asdict(result))


@router.get(
    "/topics",
    response_model=TopicListResponse,
    summary="List topics by stable ID",
    responses={503: ERROR_RESPONSES[503]},
)
def list_topics(
    service: Annotated[ProgressService, Depends(get_progress_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TopicListResponse:
    try:
        result = service.list_topics(limit=limit, offset=offset)
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Topic storage is unavailable") from exc
    return TopicListResponse(**asdict(result))


@router.get(
    "/topics/{topic_id}",
    response_model=TopicResponse,
    summary="Read one topic",
    responses={404: ERROR_RESPONSES[404], 503: ERROR_RESPONSES[503]},
)
def get_topic(
    topic_id: Annotated[str, Path(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=64)],
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> TopicResponse:
    try:
        result = service.get_topic(topic_id)
    except TopicNotFound as exc:
        raise _error(404, exc.code, "Topic was not found") from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Topic storage is unavailable") from exc
    return TopicResponse(**asdict(result))


@router.put(
    "/quizzes/{quiz_id}/topic",
    response_model=QuizTopicAssignmentResponse,
    summary="Assign or reassign a quiz without changing its snapshot",
    responses=ERROR_RESPONSES,
)
def assign_quiz_topic(
    quiz_id: Annotated[int, Path(gt=0)],
    request: QuizTopicAssignmentRequest,
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> QuizTopicAssignmentResponse:
    try:
        result = service.assign_quiz(quiz_id=quiz_id, topic_id=request.topic_id)
    except (TopicNotFound, QuizTopicNotFound) as exc:
        raise _error(404, exc.code, "Topic or quiz was not found") from exc
    except TopicInputError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Topic assignment is unavailable") from exc
    return QuizTopicAssignmentResponse(**asdict(result))


@router.get(
    "/topics/{topic_id}/progress",
    response_model=TopicProgressResponse,
    summary="Derive practice progress and a rule-based recommendation",
    responses={404: ERROR_RESPONSES[404], 503: ERROR_RESPONSES[503]},
)
def get_topic_progress(
    topic_id: Annotated[str, Path(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=64)],
    service: Annotated[ProgressService, Depends(get_progress_service)],
) -> TopicProgressResponse:
    try:
        result = service.get_progress(topic_id)
    except TopicNotFound as exc:
        raise _error(404, exc.code, "Topic was not found") from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Progress calculation is unavailable") from exc
    return TopicProgressResponse(**asdict(result))
