from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.dependencies import get_app_settings, get_document_service
from app.api.schemas.documents import (
    ChunkListResponse,
    ChunkResponse,
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    DocumentUploadResponse,
    ErrorResponse,
)
from app.core.config import Settings
from app.documents.service import DocumentNotFound, DocumentService
from app.ingestion.errors import (
    FileSizeLimitExceeded,
    IngestionError,
    UnsupportedDocumentFormat,
)
from app.ingestion.pipeline import prepare_document

router = APIRouter(prefix="/documents", tags=["documents"])

_ERROR_EXAMPLES = {
    413: {
        "model": ErrorResponse,
        "description": "The file or multipart request exceeds a configured byte limit.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "file_too_large",
                        "message": "Uploaded file exceeds the configured byte limit",
                    }
                }
            }
        },
    },
    415: {
        "model": ErrorResponse,
        "description": "The extension or detected content format is unsupported.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "unsupported_format",
                        "message": "Only .txt, .md, and text-based .pdf files are supported",
                    }
                }
            }
        },
    },
    422: {
        "model": ErrorResponse,
        "description": "The upload cannot be extracted or violates a processing limit.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "invalid_pdf",
                        "message": "The PDF is damaged or cannot be parsed",
                    }
                }
            }
        },
    },
    503: {
        "model": ErrorResponse,
        "description": "Document storage is temporarily unavailable.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "database_unavailable",
                        "message": "Document storage is temporarily unavailable",
                    }
                }
            }
        },
    },
}


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _database_error(exc: SQLAlchemyError) -> HTTPException:
    return _error(503, "database_unavailable", "Document storage is temporarily unavailable")


async def _read_upload(file: UploadFile, *, max_bytes: int) -> bytes:
    data = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise FileSizeLimitExceeded(f"Uploaded file exceeds the {max_bytes} byte limit")
    return bytes(data)


async def _request_uploads(request: Request) -> list[StarletteUploadFile]:
    form = await request.form()
    return [value for _, value in form.multi_items() if isinstance(value, StarletteUploadFile)]


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=201,
    summary="Extract, chunk, and persist one document",
    responses={
        200: {
            "model": DocumentUploadResponse,
            "description": "Identical content and extraction profile already exist.",
        },
        **_ERROR_EXAMPLES,
    },
)
async def upload_document(
    request: Request,
    response: Response,
    file: Annotated[
        UploadFile,
        File(description="One UTF-8 TXT/Markdown file or one text-based PDF"),
    ],
    settings: Annotated[Settings, Depends(get_app_settings)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentUploadResponse:
    uploads = await _request_uploads(request)
    files_to_close = {id(upload): upload for upload in [*uploads, file]}
    try:
        if len(uploads) != 1:
            raise _error(422, "one_file_required", "Exactly one uploaded file is required")

        payload = await _read_upload(file, max_bytes=settings.max_upload_size_bytes)
        prepared = await run_in_threadpool(
            prepare_document,
            payload,
            filename=file.filename,
            max_pdf_pages=settings.max_pdf_pages,
            max_characters=settings.max_extracted_characters,
            chunk_size=settings.ingestion_chunk_size,
            chunk_overlap=settings.ingestion_chunk_overlap,
        )
        result = await run_in_threadpool(service.ingest, prepared)
    except FileSizeLimitExceeded as exc:
        raise _error(413, exc.code, str(exc)) from exc
    except UnsupportedDocumentFormat as exc:
        raise _error(415, exc.code, str(exc)) from exc
    except IngestionError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    finally:
        for upload in files_to_close.values():
            await upload.close()

    response.status_code = 200 if result.duplicate else 201
    detail = DocumentDetail.model_validate(result.document)
    return DocumentUploadResponse(**detail.model_dump(), duplicate=result.duplicate)


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List ingested documents",
    responses={503: _ERROR_EXAMPLES[503]},
)
def list_documents(
    service: Annotated[DocumentService, Depends(get_document_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    try:
        page = service.list_documents(limit=limit, offset=offset)
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    return DocumentListResponse(
        items=[DocumentSummary.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetail,
    summary="Get document details and persisted reference text",
    responses={404: {"model": ErrorResponse}, 503: _ERROR_EXAMPLES[503]},
)
def get_document(
    document_id: Annotated[int, Path(gt=0)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentDetail:
    try:
        document = service.get_document(document_id)
    except DocumentNotFound as exc:
        raise _error(404, "document_not_found", "Document was not found") from exc
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    return DocumentDetail.model_validate(document)


@router.get(
    "/{document_id}/chunks",
    response_model=ChunkListResponse,
    summary="List persisted chunks for a document",
    responses={404: {"model": ErrorResponse}, 503: _ERROR_EXAMPLES[503]},
)
def list_document_chunks(
    document_id: Annotated[int, Path(gt=0)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChunkListResponse:
    try:
        page = service.list_chunks(document_id, limit=limit, offset=offset)
    except DocumentNotFound as exc:
        raise _error(404, "document_not_found", "Document was not found") from exc
    except SQLAlchemyError as exc:
        raise _database_error(exc) from exc
    return ChunkListResponse(
        items=[ChunkResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
