from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Recommendation = Literal[
    "insufficient_evidence",
    "review_material",
    "practice_more",
    "try_advanced",
]


class TopicError(RuntimeError):
    code = "topic_failed"


class TopicInputError(TopicError):
    code = "topic_input_invalid"


class TopicNotFound(TopicError):
    code = "topic_not_found"


class TopicConflict(TopicError):
    code = "topic_conflict"


class QuizTopicNotFound(TopicError):
    code = "quiz_not_found"


@dataclass(frozen=True, slots=True)
class TopicView:
    id: str
    display_name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    legacy_quizzes_assigned: int = 0


@dataclass(frozen=True, slots=True)
class TopicPage:
    items: tuple[TopicView, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class QuizTopicAssignment:
    quiz_id: int
    topic_id: str
    previous_topic_id: str | None
    changed: bool


@dataclass(frozen=True, slots=True)
class TopicProgress:
    topic_id: str
    topic_name: str
    score: float | None
    counted_questions: int
    counted_quizzes: int
    recommendation: Recommendation
    message: str
