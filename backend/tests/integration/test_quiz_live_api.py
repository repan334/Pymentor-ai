import os
import uuid
from collections.abc import Iterator
from hashlib import sha256

import pytest
from app.core.config import Settings
from app.db.models import Document, Quiz, Topic
from app.db.session import create_database_engine, get_session
from app.factory import create_app
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_QUIZ_TESTS") != "1",
    reason="set RUN_LIVE_QUIZ_TESTS=1 for bounded Gemini + Neon quiz verification",
)


def test_live_http_contract_create_get_submit_result_and_replay() -> None:
    """Use at most three inference requests without retry: index, retrieve, generate."""
    token = uuid.uuid4().hex
    content = (
        f"Phase 7 fixture {token}. Jika fungsi Python selesai tanpa return eksplisit, "
        "fungsi itu mengembalikan None."
    )
    checksum = sha256(content.encode()).hexdigest()
    settings = Settings().model_copy(update={"embedding_max_attempts": 1, "chat_max_attempts": 1})
    engine = create_database_engine(settings)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    quiz_id: int | None = None
    topic_id = f"phase-7-{token}"

    def test_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app = create_app(settings)
    app.dependency_overrides[get_session] = test_session
    try:
        with TestClient(app) as client:
            upload = client.post(
                "/api/v1/documents",
                files={"file": ("phase-7-live.txt", content.encode(), "text/plain")},
            )
            upload.raise_for_status()
            document_id = upload.json()["id"]
            indexed = client.post(f"/api/v1/documents/{document_id}/index")
            indexed.raise_for_status()
            topic = client.post(
                "/api/v1/topics",
                json={"id": topic_id, "display_name": f"Phase 7 {token}"},
            )
            topic.raise_for_status()
            created = client.post(
                "/api/v1/quizzes",
                json={
                    "topic_id": topic_id,
                    "topic": "hasil fungsi tanpa return eksplisit",
                    "document_ids": [document_id],
                    "question_count": 1,
                },
            )
            assert created.status_code < 400, created.json()
            created.raise_for_status()
            quiz = created.json()
            quiz_id = quiz["id"]
            fetched = client.get(f"/api/v1/quizzes/{quiz_id}")
            fetched.raise_for_status()

            question = quiz["questions"][0]
            submitted = client.post(
                f"/api/v1/quizzes/{quiz_id}/attempts",
                headers={"Idempotency-Key": f"phase-7-{token}"},
                json={
                    "answers": [
                        {
                            "question_id": question["id"],
                            "option_id": question["options"][0]["id"],
                        }
                    ]
                },
            )
            submitted.raise_for_status()
            attempt = submitted.json()
            result = client.get(f"/api/v1/quiz-attempts/{attempt['id']}")
            result.raise_for_status()
            replay = client.post(
                f"/api/v1/quizzes/{quiz_id}/attempts",
                headers={"Idempotency-Key": f"phase-7-{token}"},
                json={
                    "answers": [
                        {
                            "question_id": question["id"],
                            "option_id": question["options"][0]["id"],
                        }
                    ]
                },
            )

        assert created.status_code == 201
        assert fetched.json() == quiz
        assert "correct_option_id" not in created.text
        assert len(question["options"]) == 4
        assert len({option["text"].casefold() for option in question["options"]}) == 4
        assert submitted.status_code == 201
        assert result.json()["review"][0]["sources"][0]["document_id"] == document_id
        correct_id = result.json()["review"][0]["correct_option_id"]
        correct_text = next(
            option["text"] for option in question["options"] if option["id"] == correct_id
        )
        assert "none" in correct_text.casefold()
        assert "none" in result.json()["review"][0]["explanation"].casefold()
        assert replay.status_code == 200
        assert replay.json()["id"] == attempt["id"]
        assert replay.json()["idempotent_replay"] is True
    finally:
        with engine.begin() as connection:
            if quiz_id is not None:
                connection.execute(delete(Quiz).where(Quiz.id == quiz_id))
            connection.execute(delete(Topic).where(Topic.id == topic_id))
            connection.execute(delete(Document).where(Document.checksum_sha256 == checksum))
        engine.dispose()
