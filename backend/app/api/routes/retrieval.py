from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_indexing_service, get_search_service
from app.api.schemas.documents import ErrorResponse
from app.api.schemas.retrieval import (
    IndexResponse,
    IndexStatusResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
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
from app.retrieval.service import (
    DocumentNotProcessable,
    IndexChunkLimitExceeded,
    IndexDocumentNotFound,
    IndexingConflict,
    IndexingDeadlineExceeded,
    IndexingInProgress,
    IndexingService,
    SearchInputError,
    SearchService,
)

router = APIRouter(tags=["retrieval"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _map_embedding_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EmbeddingQuotaError):
        return _error(429, exc.code, "Embedding quota is currently exhausted")
    if isinstance(exc, EmbeddingAuthenticationError):
        return _error(503, exc.code, "Embedding provider authentication is unavailable")
    if isinstance(exc, EmbeddingConfigurationError):
        return _error(503, exc.code, "Embedding provider is not configured")
    if isinstance(exc, EmbeddingInvalidRequestError):
        return _error(502, exc.code, "Embedding provider rejected the request")
    if isinstance(exc, EmbeddingValidationError):
        return _error(502, exc.code, "Embedding provider returned an invalid result")
    if isinstance(exc, (EmbeddingTimeoutError, EmbeddingUnavailableError)):
        return _error(503, exc.code, "Embedding provider is temporarily unavailable")
    raise exc


_ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Document does not exist."},
    409: {"model": ErrorResponse, "description": "Indexing state changed or is busy."},
    422: {"model": ErrorResponse, "description": "Document cannot be indexed within limits."},
    429: {"model": ErrorResponse, "description": "Embedding quota is exhausted."},
    502: {"model": ErrorResponse, "description": "Embedding response is invalid."},
    503: {"model": ErrorResponse, "description": "Database or provider is unavailable."},
}


@router.post(
    "/documents/{document_id}/index",
    response_model=IndexResponse,
    summary="Synchronously embed every chunk of one processed document",
    responses=_ERROR_RESPONSES,
)
def index_document(
    document_id: Annotated[int, Path(gt=0)],
    service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> IndexResponse:
    try:
        result = service.index_document(document_id)
    except IndexDocumentNotFound as exc:
        raise _error(404, exc.code, "Document was not found") from exc
    except (DocumentNotProcessable, IndexChunkLimitExceeded) as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except (IndexingInProgress, IndexingConflict) as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except IndexingDeadlineExceeded as exc:
        raise _error(503, exc.code, "Indexing exceeded its configured time limit") from exc
    except (
        EmbeddingAuthenticationError,
        EmbeddingConfigurationError,
        EmbeddingInvalidRequestError,
        EmbeddingQuotaError,
        EmbeddingTimeoutError,
        EmbeddingUnavailableError,
        EmbeddingValidationError,
    ) as exc:
        raise _map_embedding_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Document storage is unavailable") from exc
    return IndexResponse(**asdict(result))


@router.get(
    "/documents/{document_id}/index-status",
    response_model=IndexStatusResponse,
    summary="Inspect ingestion and embedding readiness separately",
    responses={404: _ERROR_RESPONSES[404], 503: _ERROR_RESPONSES[503]},
)
def get_index_status(
    document_id: Annotated[int, Path(gt=0)],
    service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> IndexStatusResponse:
    try:
        status = service.get_status(document_id)
    except IndexDocumentNotFound as exc:
        raise _error(404, exc.code, "Document was not found") from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Document storage is unavailable") from exc
    return IndexStatusResponse(**asdict(status))


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Find nearest compatible chunks with exact cosine distance",
    responses={
        422: _ERROR_RESPONSES[422],
        429: _ERROR_RESPONSES[429],
        502: _ERROR_RESPONSES[502],
        503: _ERROR_RESPONSES[503],
    },
)
def search(
    request: SearchRequest,
    service: Annotated[SearchService, Depends(get_search_service)],
) -> SearchResponse:
    try:
        result = service.search(
            query=request.query,
            top_k=request.top_k,
            document_ids=request.document_ids,
        )
    except SearchInputError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except (
        EmbeddingAuthenticationError,
        EmbeddingConfigurationError,
        EmbeddingInvalidRequestError,
        EmbeddingQuotaError,
        EmbeddingTimeoutError,
        EmbeddingUnavailableError,
        EmbeddingValidationError,
    ) as exc:
        raise _map_embedding_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _error(503, "database_unavailable", "Document storage is unavailable") from exc
    return SearchResponse(
        query=result.query,
        top_k=result.top_k,
        embedding_profile=result.embedding_profile,
        results=[SearchHitResponse(**asdict(item)) for item in result.results],
        reason=result.reason,
    )
