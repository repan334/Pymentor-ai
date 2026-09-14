import os
import uuid
from datetime import UTC, datetime

import pytest
from app.core.config import Settings
from app.db.models import Quiz, QuizAttempt, QuizOption, QuizQuestion, Topic
from app.db.session import create_database_engine
from app.progress.service import ProgressService
from app.quiz.models import SubmittedAnswer
from app.quiz.service import QuizService
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 to test the configured Neon database",
    ),
]


def _quiz(topic_snapshot: str, topic_id: str | None, question_count: int = 5) -> Quiz:
    return Quiz(
        topic_id=topic_id,
        topic=topic_snapshot,
        question_count=question_count,
        document_ids=[],
        llm_provider="fixture",
        llm_model="fixture",
        prompt_version="fixture-v1",
        generation_profile="fixture:fixture:fixture-v1",
    )


def _attempt(
    quiz_id: int,
    key: str,
    correct: int,
    total: int,
    created_at: datetime,
) -> QuizAttempt:
    return QuizAttempt(
        quiz_id=quiz_id,
        idempotency_key=key,
        payload_sha256=(key.encode().hex() + "0" * 64)[:64],
        correct_count=correct,
        total_questions=total,
        percentage=correct * 100 / total,
        created_at=created_at,
    )


def test_neon_topic_assignment_latest_attempt_progress_and_isolation() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    token = uuid.uuid4().hex
    exact_name = f"Legacy Exact {token}"
    ambiguous_name = f"Legacy Ambiguous {token}"
    topic_a = f"functions-{token}"
    topic_b = f"loops-{token}"
    topic_small = f"small-{token}"
    quiz_ids: list[int] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            exact_legacy = _quiz(exact_name, None)
            ambiguous_legacy = _quiz(ambiguous_name, None)
            session.add_all([exact_legacy, ambiguous_legacy])
            session.commit()
            quiz_ids.extend([exact_legacy.id, ambiguous_legacy.id])

            service = ProgressService(session)
            created_a = service.create_topic(
                topic_id=topic_a, display_name=exact_name, description="Fixture functions"
            )
            assert created_a.legacy_quizzes_assigned == 1
            session.refresh(exact_legacy)
            session.refresh(ambiguous_legacy)
            assert exact_legacy.topic_id == topic_a
            assert ambiguous_legacy.topic_id is None

            service.create_topic(
                topic_id=topic_b,
                display_name=f"Loops {token}",
                description=None,
            )
            service.create_topic(
                topic_id=topic_small,
                display_name=f"Small {token}",
                description=None,
            )
            second_a = _quiz(f"Second A {token}", topic_a)
            only_b = _quiz(f"Only B {token}", topic_b)
            small = _quiz(f"Small quiz {token}", topic_small, question_count=3)
            session.add_all([second_a, only_b, small])
            session.commit()
            quiz_ids.extend([second_a.id, only_b.id, small.id])

            same_time = datetime(2026, 9, 14, tzinfo=UTC)
            session.add_all(
                [
                    _attempt(exact_legacy.id, f"old-{token}", 5, 5, same_time),
                    _attempt(exact_legacy.id, f"new-{token}", 3, 5, same_time),
                    _attempt(second_a.id, f"second-{token}", 4, 5, same_time),
                    _attempt(only_b.id, f"b-{token}", 5, 5, same_time),
                    _attempt(small.id, f"small-{token}", 2, 3, same_time),
                ]
            )
            session.commit()

            progress_a = service.get_progress(topic_a)
            progress_b = service.get_progress(topic_b)
            progress_small = service.get_progress(topic_small)
            assert (progress_a.score, progress_a.counted_questions, progress_a.counted_quizzes) == (
                70.0,
                10,
                2,
            )
            assert progress_a.recommendation == "practice_more"
            assert progress_b.score == 100.0
            assert progress_b.recommendation == "try_advanced"
            assert progress_small.score == 66.67
            assert progress_small.recommendation == "insufficient_evidence"

            assignment = service.assign_quiz(quiz_id=ambiguous_legacy.id, topic_id=topic_b)
            assert assignment.previous_topic_id is None
            assert assignment.changed is True
            assert (
                service.assign_quiz(quiz_id=ambiguous_legacy.id, topic_id=topic_b).changed is False
            )
    finally:
        with engine.begin() as connection:
            if quiz_ids:
                connection.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))
            connection.execute(delete(Topic).where(Topic.id.in_([topic_a, topic_b, topic_small])))
        engine.dispose()


def test_neon_idempotent_replay_does_not_change_derived_progress() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    token = uuid.uuid4().hex
    topic_id = f"replay-{token}"
    quiz_id: int | None = None
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                Topic(id=topic_id, display_name=f"Replay {token}", normalized_name=topic_id)
            )
            quiz = _quiz(f"Replay {token}", topic_id)
            for question_index in range(5):
                question = QuizQuestion(
                    question_index=question_index,
                    prompt=f"Question {question_index}",
                    explanation="Fixture explanation",
                )
                question.options = [
                    QuizOption(
                        option_index=index,
                        text=f"Option {question_index}-{index}",
                        is_correct=index == 0,
                    )
                    for index in range(4)
                ]
                quiz.questions.append(question)
            session.add(quiz)
            session.commit()
            quiz_id = quiz.id
            answers = [
                SubmittedAnswer(question_id=question.id, option_id=question.options[0].id)
                for question in quiz.questions
            ]
            quiz_service = QuizService(session, None, None, settings)  # type: ignore[arg-type]
            first = quiz_service.submit_attempt(
                quiz_id=quiz.id, idempotency_key=f"replay-{token}", answers=answers
            )
            before = ProgressService(session).get_progress(topic_id)
            replay = quiz_service.submit_attempt(
                quiz_id=quiz.id, idempotency_key=f"replay-{token}", answers=answers
            )
            after = ProgressService(session).get_progress(topic_id)

            assert replay.id == first.id
            assert replay.idempotent_replay is True
            assert before == after
            assert before.counted_questions == 5
            assert (
                session.scalar(
                    select(func.count(QuizAttempt.id)).where(QuizAttempt.quiz_id == quiz.id)
                )
                == 1
            )
    finally:
        with engine.begin() as connection:
            if quiz_id is not None:
                connection.execute(delete(Quiz).where(Quiz.id == quiz_id))
            connection.execute(delete(Topic).where(Topic.id == topic_id))
        engine.dispose()
