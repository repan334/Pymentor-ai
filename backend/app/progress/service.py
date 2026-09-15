from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Quiz, QuizAttempt, Topic
from app.progress.models import (
    Difficulty,
    QuizTopicAssignment,
    QuizTopicNotFound,
    Recommendation,
    TopicConflict,
    TopicInputError,
    TopicNotFound,
    TopicPage,
    TopicProgress,
    TopicView,
)

TOPIC_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MIN_EVIDENCE_QUESTIONS = 5

_MESSAGES: dict[Recommendation, str] = {
    "insufficient_evidence": (
        "Belum cukup soal yang dihitung untuk memberi rekomendasi berbasis latihan."
    ),
    "review_material": "Tinjau kembali materi dasar topik ini sebelum mencoba quiz lagi.",
    "practice_more": "Lanjutkan latihan pada topik ini untuk memperkuat konsistensi.",
    "try_advanced": "Coba materi atau latihan yang lebih menantang pada topik ini.",
}


class ProgressService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_topic(
        self,
        *,
        topic_id: str,
        display_name: str,
        description: str | None,
    ) -> TopicView:
        topic_id = validate_topic_id(topic_id)
        display_name = _clean_display_name(display_name)
        description = _clean_description(description)
        normalized_name = _normalize_name(display_name)
        if len(normalized_name) > 120:
            raise TopicInputError("Normalized display name must not exceed 120 characters")
        topic = Topic(
            id=topic_id,
            display_name=display_name,
            normalized_name=normalized_name,
            description=description,
        )
        try:
            self.session.add(topic)
            self.session.flush()
            assigned = self._assign_unambiguous_legacy_quizzes(topic)
            self.session.commit()
            self.session.refresh(topic)
        except IntegrityError as exc:
            self.session.rollback()
            raise TopicConflict("Topic ID or display name already exists") from exc
        except Exception:
            self.session.rollback()
            raise
        return _topic_view(topic, legacy_quizzes_assigned=assigned)

    def list_topics(self, *, limit: int, offset: int) -> TopicPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise TopicInputError("Pagination is outside the allowed range")
        total = self.session.scalar(select(func.count(Topic.id))) or 0
        rows = self.session.scalars(
            select(Topic).order_by(Topic.id).limit(limit).offset(offset)
        ).all()
        return TopicPage(
            items=tuple(_topic_view(topic) for topic in rows),
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_topic(self, topic_id: str) -> TopicView:
        topic = self._require_topic(topic_id)
        return _topic_view(topic)

    def assign_quiz(self, *, quiz_id: int, topic_id: str) -> QuizTopicAssignment:
        topic = self._require_topic(topic_id)
        quiz = self.session.get(Quiz, quiz_id)
        if quiz is None:
            raise QuizTopicNotFound(quiz_id)
        previous = quiz.topic_id
        if previous == topic.id:
            self.session.rollback()
            return QuizTopicAssignment(
                quiz_id=quiz.id,
                topic_id=topic.id,
                previous_topic_id=previous,
                changed=False,
            )
        try:
            quiz.topic_id = topic.id
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return QuizTopicAssignment(
            quiz_id=quiz.id,
            topic_id=topic.id,
            previous_topic_id=previous,
            changed=True,
        )

    def get_progress(self, topic_id: str) -> TopicProgress:
        topic = self._require_topic(topic_id)
        latest = select(
            QuizAttempt.quiz_id.label("quiz_id"),
            QuizAttempt.correct_count.label("correct_count"),
            QuizAttempt.total_questions.label("total_questions"),
            func.row_number()
            .over(
                partition_by=QuizAttempt.quiz_id,
                order_by=(QuizAttempt.created_at.desc(), QuizAttempt.id.desc()),
            )
            .label("attempt_rank"),
        ).subquery()
        totals = self.session.execute(
            select(
                func.coalesce(func.sum(latest.c.correct_count), 0),
                func.coalesce(func.sum(latest.c.total_questions), 0),
                func.count(latest.c.quiz_id),
            )
            .join(Quiz, Quiz.id == latest.c.quiz_id)
            .where(Quiz.topic_id == topic.id, latest.c.attempt_rank == 1)
        ).one()
        score, recommendation = calculate_topic_progress(
            correct_questions=int(totals[0]),
            counted_questions=int(totals[1]),
        )
        return TopicProgress(
            topic_id=topic.id,
            topic_name=topic.display_name,
            score=None if score is None else float(score),
            counted_questions=int(totals[1]),
            counted_quizzes=int(totals[2]),
            recommendation=recommendation,
            message=_MESSAGES[recommendation],
        )

    def _require_topic(self, topic_id: str) -> Topic:
        topic_id = validate_topic_id(topic_id)
        topic = self.session.get(Topic, topic_id)
        if topic is None:
            raise TopicNotFound(topic_id)
        return topic

    def _assign_unambiguous_legacy_quizzes(self, topic: Topic) -> int:
        candidates = self.session.scalars(select(Quiz).where(Quiz.topic_id.is_(None))).all()
        matching = [
            quiz for quiz in candidates if _normalize_name(quiz.topic) == topic.normalized_name
        ]
        for quiz in matching:
            quiz.topic_id = topic.id
        return len(matching)


def calculate_topic_progress(
    *,
    correct_questions: int,
    counted_questions: int,
) -> tuple[Decimal | None, Recommendation]:
    if correct_questions < 0 or counted_questions < 0 or correct_questions > counted_questions:
        raise ValueError("Question counts are inconsistent")
    if counted_questions == 0:
        return None, "insufficient_evidence"
    score = (Decimal(correct_questions) * Decimal(100) / Decimal(counted_questions)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if counted_questions < MIN_EVIDENCE_QUESTIONS:
        return score, "insufficient_evidence"
    if score < Decimal("60"):
        return score, "review_material"
    if score < Decimal("80"):
        return score, "practice_more"
    return score, "try_advanced"


def derive_difficulty(recommendation: Recommendation) -> Difficulty:
    if recommendation == "try_advanced":
        return "advanced"
    if recommendation == "practice_more":
        return "intermediate"
    return "basic"


def validate_topic_id(value: str) -> str:
    value = value.strip()
    if len(value) > 64 or not TOPIC_ID_PATTERN.fullmatch(value):
        raise TopicInputError(
            "Topic ID must be a lowercase slug (letters, numbers, hyphens; maximum 64)"
        )
    return value


def _clean_display_name(value: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > 120:
        raise TopicInputError("Display name must contain 1 to 120 characters")
    return value


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    if len(value) > 500:
        raise TopicInputError("Description must not exceed 500 characters")
    return value or None


def _normalize_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _topic_view(topic: Topic, *, legacy_quizzes_assigned: int = 0) -> TopicView:
    return TopicView(
        id=topic.id,
        display_name=topic.display_name,
        description=topic.description,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
        legacy_quizzes_assigned=legacy_quizzes_assigned,
    )
