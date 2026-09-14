from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TopicCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
        examples=["python-functions"],
    )
    display_name: str = Field(min_length=1, max_length=120, examples=["Fungsi Python"])
    description: str | None = Field(default=None, max_length=500)


class TopicResponse(BaseModel):
    id: str
    display_name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    legacy_quizzes_assigned: int


class TopicListResponse(BaseModel):
    items: list[TopicResponse]
    total: int
    limit: int
    offset: int


class QuizTopicAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    )


class QuizTopicAssignmentResponse(BaseModel):
    quiz_id: int
    topic_id: str
    previous_topic_id: str | None
    changed: bool


class TopicProgressResponse(BaseModel):
    topic_id: str
    topic_name: str
    score: float | None = Field(
        description="Practice-performance percentage, not validated mastery."
    )
    counted_questions: int
    counted_quizzes: int
    recommendation: Literal[
        "insufficient_evidence",
        "review_material",
        "practice_more",
        "try_advanced",
    ]
    message: str
