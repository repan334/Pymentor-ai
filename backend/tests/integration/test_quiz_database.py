import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from app.core.config import Settings
from app.db.models import Quiz, QuizAttempt, Topic
from app.db.session import create_database_engine
from app.quiz.models import GeneratedQuizOutput, GeneratedQuizQuestion, SubmittedAnswer
from app.quiz.service import QuizService
from app.retrieval.service import SearchHit, SearchResult
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 to test the configured Neon database",
    ),
]


class DatabaseQuizSearch:
    def __init__(self, session: Session, document_id: int) -> None:
        self.session = session
        self.document_id = document_id

    def search(self, **kwargs: object) -> SearchResult:
        assert self.session.in_transaction() is False
        content = "Fungsi tanpa return eksplisit menghasilkan None."
        return SearchResult(
            query=str(kwargs["query"]),
            top_k=int(kwargs["top_k"]),
            embedding_profile="gemini:gemini-embedding-2:768:retrieval-asymmetric-v1",
            results=(
                SearchHit(
                    chunk_id=987654,
                    document_id=self.document_id,
                    source_name="phase-7-fixture.md",
                    content=content,
                    start_char=0,
                    end_char=len(content),
                    page_number=None,
                    metadata={"fixture": True},
                    cosine_distance=0.1,
                ),
            ),
        )


class DatabaseQuizChat:
    profile = "gemini:gemini-3.6-flash:grounded-tutor-v2"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.calls = 0

    def generate_structured(self, **kwargs: object) -> GeneratedQuizOutput:
        assert self.session.in_transaction() is False
        self.calls += 1
        return GeneratedQuizOutput(
            status="ready",
            questions=[
                GeneratedQuizQuestion(
                    question="Apa hasil fungsi tanpa return eksplisit?",
                    options=["None", "0", "False", "Error"],
                    correct_option_index=0,
                    explanation="Materi menyatakan fungsi tersebut menghasilkan None.",
                    reference_ids=["S1"],
                )
            ],
        )


class RacingQuizService(QuizService):
    def __init__(self, *args: object, barrier: Barrier, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._barrier = barrier
        self._attempt_lookup_count = 0

    def _find_attempt(self, quiz_id: int, key: str) -> QuizAttempt | None:
        result = super()._find_attempt(quiz_id, key)
        self._attempt_lookup_count += 1
        if self._attempt_lookup_count == 1:
            self._barrier.wait(timeout=10)
        return result


def test_neon_quiz_snapshot_scoring_idempotency_and_unique_constraint() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    token = uuid.uuid4().hex
    topic = f"phase-7-{token}"
    document_id = 900_000_000 + int(token[:6], 16)
    quiz_id: int | None = None
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(Topic(id=topic, display_name=topic, normalized_name=topic))
            session.commit()
            chat = DatabaseQuizChat(session)
            service = QuizService(session, DatabaseQuizSearch(session, document_id), chat, settings)
            public_quiz = service.create_quiz(
                topic_id=topic, topic=topic, document_ids=[document_id], question_count=1
            )
            quiz_id = public_quiz.id
            assert chat.calls == 1
            assert not hasattr(public_quiz.questions[0], "correct_option_id")
            correct_option = public_quiz.questions[0].options[0]
            answer = SubmittedAnswer(
                question_id=public_quiz.questions[0].id,
                option_id=correct_option.id,
            )

            first = service.submit_attempt(
                quiz_id=quiz_id, idempotency_key="same-key", answers=[answer]
            )
            replay = service.submit_attempt(
                quiz_id=quiz_id, idempotency_key="same-key", answers=[answer]
            )
            wrong = service.submit_attempt(
                quiz_id=quiz_id,
                idempotency_key="new-key",
                answers=[
                    SubmittedAnswer(
                        question_id=public_quiz.questions[0].id,
                        option_id=public_quiz.questions[0].options[1].id,
                    )
                ],
            )

            assert first.correct_count == 1
            assert first.percentage == 100.0
            assert first.review[0].correct_option_id == correct_option.id
            assert first.review[0].sources[0].document_id == document_id
            assert replay.id == first.id
            assert replay.idempotent_replay is True
            assert wrong.correct_count == 0
            assert wrong.percentage == 0.0

            duplicate = QuizAttempt(
                quiz_id=quiz_id,
                idempotency_key="same-key",
                payload_sha256="a" * 64,
                correct_count=0,
                total_questions=1,
                percentage=Decimal("0.00"),
            )
            session.add(duplicate)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            assert session.scalar(select(func.count(Quiz.id)).where(Quiz.id == quiz_id)) == 1

        barrier = Barrier(2)
        session_factory = sessionmaker(engine, expire_on_commit=False)

        def submit_concurrently() -> int:
            with session_factory() as racing_session:
                service = RacingQuizService(
                    racing_session,
                    DatabaseQuizSearch(racing_session, document_id),
                    DatabaseQuizChat(racing_session),
                    settings,
                    barrier=barrier,
                )
                result = service.submit_attempt(
                    quiz_id=quiz_id,
                    idempotency_key="concurrent-key",
                    answers=[answer],
                )
                return result.id

        with ThreadPoolExecutor(max_workers=2) as executor:
            attempt_ids = list(executor.map(lambda _: submit_concurrently(), range(2)))
        assert attempt_ids[0] == attempt_ids[1]
    finally:
        with engine.begin() as connection:
            if quiz_id is not None:
                connection.execute(delete(Quiz).where(Quiz.id == quiz_id))
            connection.execute(delete(Topic).where(Topic.id == topic))
        engine.dispose()


def test_neon_quiz_transaction_failure_leaves_no_partial_snapshot() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    token = uuid.uuid4().hex
    topic = f"phase-7-rollback-{token}"
    document_id = 910_000_000 + int(token[:6], 16)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(Topic(id=topic, display_name=topic, normalized_name=topic))
            session.commit()
            service = QuizService(
                session,
                DatabaseQuizSearch(session, document_id),
                DatabaseQuizChat(session),
                settings,
            )

            def abort_commit(_: Session) -> None:
                raise RuntimeError("simulated commit failure")

            event.listen(session, "before_commit", abort_commit, once=True)
            with pytest.raises(RuntimeError, match="simulated commit failure"):
                service.create_quiz(
                    topic_id=topic,
                    topic=topic,
                    document_ids=[document_id],
                    question_count=1,
                )

        with Session(engine) as verification_session:
            assert (
                verification_session.scalar(select(func.count(Quiz.id)).where(Quiz.topic == topic))
                == 0
            )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Quiz).where(Quiz.topic == topic))
            connection.execute(delete(Topic).where(Topic.id == topic))
        engine.dispose()
