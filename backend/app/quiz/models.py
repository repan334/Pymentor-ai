from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class GeneratedQuizQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    explanation: str
    reference_ids: list[str] = Field(min_length=1, max_length=8)


class GeneratedQuizOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "insufficient_context"]
    questions: list[GeneratedQuizQuestion] = Field(default_factory=list, max_length=5)


class QuizGenerationAdapter(Protocol):
    @property
    def profile(self) -> str: ...

    def generate_structured(self, **kwargs: Any) -> BaseModel: ...


class QuizError(RuntimeError):
    code = "quiz_failed"


class QuizInputError(QuizError):
    code = "quiz_input_invalid"


class QuizInsufficientContext(QuizError):
    code = "quiz_insufficient_context"


class QuizOutputInvalid(QuizError):
    code = "quiz_output_invalid"


class QuizNotFound(QuizError):
    code = "quiz_not_found"


class AttemptNotFound(QuizError):
    code = "quiz_attempt_not_found"


class AttemptInputError(QuizError):
    code = "quiz_attempt_invalid"


class IdempotencyConflict(QuizError):
    code = "idempotency_conflict"


@dataclass(frozen=True, slots=True)
class QuizOptionView:
    id: int
    text: str


@dataclass(frozen=True, slots=True)
class QuizQuestionView:
    id: int
    question: str
    options: tuple[QuizOptionView, ...]


@dataclass(frozen=True, slots=True)
class QuizView:
    id: int
    topic_id: str | None
    topic: str
    question_count: int
    questions: tuple[QuizQuestionView, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SubmittedAnswer:
    question_id: int
    option_id: int


@dataclass(frozen=True, slots=True)
class QuizSourceView:
    reference_id: str
    document_id: int
    chunk_id: int
    source_name: str
    start_char: int
    end_char: int
    excerpt: str
    page_number: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class QuestionReview:
    question_id: int
    selected_option_id: int
    correct_option_id: int
    is_correct: bool
    explanation: str
    sources: tuple[QuizSourceView, ...]


@dataclass(frozen=True, slots=True)
class AttemptView:
    id: int
    quiz_id: int
    correct_count: int
    question_count: int
    percentage: float
    review: tuple[QuestionReview, ...]
    created_at: datetime
    idempotent_replay: bool = False
