from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    top_k: int = Field(default=4, ge=1, le=20)
    document_ids: list[PositiveInt] | None = None

    @field_validator("question")
    @classmethod
    def question_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace text")
        return value

    @field_validator("document_ids")
    @classmethod
    def document_ids_must_be_unique(
        cls, value: list[PositiveInt] | None
    ) -> list[PositiveInt] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("document_ids must not contain duplicates")
        return value


class CitationResponse(BaseModel):
    reference_id: str
    document_id: int
    chunk_id: int
    source_name: str
    start_char: int
    end_char: int
    excerpt: str
    page_number: int | None
    metadata: dict[str, Any]


class ChatResponse(BaseModel):
    status: Literal["answered", "insufficient_context"]
    answer: str
    citations: list[CitationResponse]
