from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_name: str
    source_type: str
    file_size_bytes: int
    checksum_sha256: str
    extraction_profile: str
    status: str
    character_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    reference_text: str
    metadata: dict[str, Any]


class DocumentUploadResponse(DocumentDetail):
    duplicate: bool


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    chunk_index: int
    content: str
    start_char: int
    end_char: int
    page_number: int | None
    metadata: dict[str, Any]


class ChunkListResponse(BaseModel):
    items: list[ChunkResponse]
    total: int
    limit: int
    offset: int


PaginationLimit = Field(default=20, ge=1, le=100, description="Items per page (maximum 100)")
PaginationOffset = Field(default=0, ge=0, description="Number of items to skip")
