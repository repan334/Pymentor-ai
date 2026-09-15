from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class QuizCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    topic: str
    document_ids: list[PositiveInt] | None = None
    question_count: int = Field(default=3, ge=1, le=5)

    @field_validator("topic")
    @classmethod
    def topic_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic must contain non-whitespace text")
        return value

    @field_validator("document_ids")
    @classmethod
    def document_ids_must_be_unique(
        cls, value: list[PositiveInt] | None
    ) -> list[PositiveInt] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("document_ids must not contain duplicates")
        return value


class QuizOptionResponse(BaseModel):
    id: int
    text: str


class QuizQuestionResponse(BaseModel):
    id: int
    question: str
    options: list[QuizOptionResponse]


class QuizResponse(BaseModel):
    id: int
    topic_id: str | None
    topic: str
    question_count: int
    questions: list[QuizQuestionResponse]
    created_at: datetime


class QuizSummaryResponse(BaseModel):
    id: int
    topic_id: str | None
    topic: str
    question_count: int
    created_at: datetime


class QuizListResponse(BaseModel):
    items: list[QuizSummaryResponse]
    total: int
    limit: int
    offset: int


class AnswerSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: PositiveInt
    option_id: PositiveInt


class AttemptCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[AnswerSubmission] = Field(min_length=1, max_length=5)


class QuizSourceResponse(BaseModel):
    reference_id: str
    document_id: int
    chunk_id: int
    source_name: str
    start_char: int
    end_char: int
    excerpt: str
    page_number: int | None
    metadata: dict[str, Any]


class QuestionReviewResponse(BaseModel):
    question_id: int
    selected_option_id: int
    correct_option_id: int
    is_correct: bool
    explanation: str
    sources: list[QuizSourceResponse]


class AttemptResponse(BaseModel):
    id: int
    quiz_id: int
    correct_count: int
    question_count: int
    percentage: float
    review: list[QuestionReviewResponse]
    created_at: datetime
    idempotent_replay: bool


class AttemptSummaryResponse(BaseModel):
    id: int
    quiz_id: int
    correct_count: int
    question_count: int
    percentage: float
    created_at: datetime


class AttemptListResponse(BaseModel):
    items: list[AttemptSummaryResponse]
    total: int
    limit: int
    offset: int
