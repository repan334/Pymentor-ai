from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, PositiveInt, field_validator


class EmbeddingProfileResponse(BaseModel):
    provider: str
    model: str
    dimensions: int
    input_version: str
    key: str


class IndexResponse(BaseModel):
    document_id: int
    indexing_status: str
    indexed_chunk_count: int
    embedding_profile: str
    idempotent: bool


class IndexStatusResponse(BaseModel):
    document_id: int
    ingestion_status: str
    indexing_status: str
    eligible_for_search: bool
    embedding_profile: str | None
    embedded_chunk_count: int
    chunk_count: int
    indexing_started_at: datetime | None
    indexed_at: datetime | None
    error_code: str | None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=3, ge=1, le=20)
    document_ids: list[PositiveInt] | None = None

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must contain non-whitespace text")
        return value

    @field_validator("document_ids")
    @classmethod
    def document_ids_must_be_unique(
        cls, value: list[PositiveInt] | None
    ) -> list[PositiveInt] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("document_ids must not contain duplicates")
        return value


class SearchHitResponse(BaseModel):
    chunk_id: int
    document_id: int
    source_name: str
    content: str
    start_char: int
    end_char: int
    page_number: int | None
    metadata: dict[str, Any]
    cosine_distance: float = Field(
        description="Lower is closer; this is not confidence or proof of correctness."
    )


class SearchResponse(BaseModel):
    query: str
    top_k: int
    embedding_profile: str
    results: list[SearchHitResponse]
    reason: str | None = Field(
        default=None,
        description="Why no provider call/results were needed when the result set is empty.",
    )
