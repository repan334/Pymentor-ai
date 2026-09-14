from datetime import UTC, datetime
from typing import Any

import pytest
from app.api.dependencies import get_quiz_service
from app.core.config import Settings
from app.factory import create_app
from app.quiz.models import (
    AttemptInputError,
    AttemptNotFound,
    AttemptView,
    IdempotencyConflict,
    QuestionReview,
    QuizNotFound,
    QuizOptionView,
    QuizQuestionView,
    QuizSourceView,
    QuizView,
)
from fastapi.testclient import TestClient


def _quiz() -> QuizView:
    return QuizView(
        id=10,
        topic_id="python-functions",
        topic="fungsi Python",
        question_count=1,
        questions=(
            QuizQuestionView(
                id=20,
                question="Apa hasil fungsi tanpa return eksplisit?",
                options=tuple(
                    QuizOptionView(id=30 + index, text=text)
                    for index, text in enumerate(("None", "0", "False", "Error"))
                ),
            ),
        ),
        created_at=datetime(2026, 9, 14, tzinfo=UTC),
    )


def _attempt(*, replay: bool = False, correct: bool = True) -> AttemptView:
    return AttemptView(
        id=40,
        quiz_id=10,
        correct_count=1 if correct else 0,
        question_count=1,
        percentage=100.0 if correct else 0.0,
        review=(
            QuestionReview(
                question_id=20,
                selected_option_id=30 if correct else 31,
                correct_option_id=30,
                is_correct=correct,
                explanation="Tanpa return eksplisit, fungsi menghasilkan None.",
                sources=(
                    QuizSourceView(
                        reference_id="S1",
                        document_id=2,
                        chunk_id=5,
                        source_name="fungsi.md",
                        start_char=0,
                        end_char=47,
                        excerpt="Fungsi tanpa return eksplisit menghasilkan None.",
                        page_number=None,
                        metadata={"document_id": 2},
                    ),
                ),
            ),
        ),
        created_at=datetime(2026, 9, 14, tzinfo=UTC),
        idempotent_replay=replay,
    )


class FakeQuizService:
    def __init__(self) -> None:
        self.create_result: QuizView | Exception = _quiz()
        self.get_result: QuizView | Exception = _quiz()
        self.attempt_result: AttemptView | Exception = _attempt()
        self.get_attempt_result: AttemptView | Exception = _attempt()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_quiz(self, **kwargs: Any) -> QuizView:
        self.calls.append(("create", kwargs))
        if isinstance(self.create_result, Exception):
            raise self.create_result
        return self.create_result

    def get_quiz(self, quiz_id: int) -> QuizView:
        if isinstance(self.get_result, Exception):
            raise self.get_result
        return self.get_result

    def submit_attempt(self, **kwargs: Any) -> AttemptView:
        self.calls.append(("submit", kwargs))
        if isinstance(self.attempt_result, Exception):
            raise self.attempt_result
        return self.attempt_result

    def get_attempt(self, attempt_id: int) -> AttemptView:
        if isinstance(self.get_attempt_result, Exception):
            raise self.get_attempt_result
        return self.get_attempt_result


def _client(service: FakeQuizService) -> TestClient:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_quiz_service] = lambda: service
    return TestClient(app)


def test_create_and_get_hide_key_explanation_and_sources() -> None:
    service = FakeQuizService()
    with _client(service) as client:
        created = client.post(
            "/api/v1/quizzes",
            json={
                "topic_id": "python-functions",
                "topic": "fungsi Python",
                "document_ids": [2],
                "question_count": 1,
            },
        )
        fetched = client.get("/api/v1/quizzes/10")

    assert created.status_code == 201
    assert fetched.status_code == 200
    assert service.calls[0][1]["topic_id"] == "python-functions"
    for payload in (created.json(), fetched.json()):
        assert payload["topic_id"] == "python-functions"
        serialized = str(payload)
        assert "correct_option" not in serialized
        assert "is_correct" not in serialized
        assert "explanation" not in serialized
        assert "sources" not in serialized
        assert payload["questions"][0]["options"] == [
            {"id": 30, "text": "None"},
            {"id": 31, "text": "0"},
            {"id": 32, "text": "False"},
            {"id": 33, "text": "Error"},
        ]


def test_submit_reveals_review_only_after_complete_submission() -> None:
    service = FakeQuizService()
    response = _client(service).post(
        "/api/v1/quizzes/10/attempts",
        headers={"Idempotency-Key": "attempt-1"},
        json={"answers": [{"question_id": 20, "option_id": 30}]},
    )

    assert response.status_code == 201
    assert response.json()["percentage"] == 100.0
    assert response.json()["review"][0]["correct_option_id"] == 30
    assert response.json()["review"][0]["sources"][0]["reference_id"] == "S1"


def test_idempotent_replay_is_200_and_payload_conflict_is_409() -> None:
    replay_service = FakeQuizService()
    replay_service.attempt_result = _attempt(replay=True)
    replay = _client(replay_service).post(
        "/api/v1/quizzes/10/attempts",
        headers={"Idempotency-Key": "same"},
        json={"answers": [{"question_id": 20, "option_id": 30}]},
    )
    conflict_service = FakeQuizService()
    conflict_service.attempt_result = IdempotencyConflict("different payload")
    conflict = _client(conflict_service).post(
        "/api/v1/quizzes/10/attempts",
        headers={"Idempotency-Key": "same"},
        json={"answers": [{"question_id": 20, "option_id": 31}]},
    )

    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"topic_id": "python-functions", "topic": ""},
        {"topic_id": "python-functions", "topic": "valid", "question_count": 0},
        {"topic_id": "python-functions", "topic": "valid", "question_count": 6},
        {"topic_id": "python-functions", "topic": "valid", "document_ids": [1, 1]},
        {"topic_id": "INVALID", "topic": "valid"},
        {"topic_id": "python-functions", "topic": "valid", "correct_option_id": 1},
    ],
)
def test_create_rejects_invalid_or_key_control_fields(payload: dict[str, Any]) -> None:
    assert _client(FakeQuizService()).post("/api/v1/quizzes", json=payload).status_code == 422


def test_attempt_rejects_missing_key_and_service_validation() -> None:
    client = _client(FakeQuizService())
    missing_key = client.post(
        "/api/v1/quizzes/10/attempts",
        json={"answers": [{"question_id": 20, "option_id": 30}]},
    )
    service = FakeQuizService()
    service.attempt_result = AttemptInputError("incomplete")
    incomplete = _client(service).post(
        "/api/v1/quizzes/10/attempts",
        headers={"Idempotency-Key": "key"},
        json={"answers": [{"question_id": 20, "option_id": 30}]},
    )

    assert missing_key.status_code == 422
    assert incomplete.status_code == 422
    assert incomplete.json()["detail"]["code"] == "quiz_attempt_invalid"


def test_not_found_and_openapi_contracts() -> None:
    service = FakeQuizService()
    service.get_result = QuizNotFound(99)
    service.get_attempt_result = AttemptNotFound(99)
    with _client(service) as client:
        assert client.get("/api/v1/quizzes/99").status_code == 404
        assert client.get("/api/v1/quiz-attempts/99").status_code == 404
        schema = client.get("/openapi.json").json()

    paths = schema["paths"]
    assert "/api/v1/quizzes" in paths
    assert "/api/v1/quizzes/{quiz_id}" in paths
    assert "/api/v1/quizzes/{quiz_id}/attempts" in paths
    assert "/api/v1/quiz-attempts/{attempt_id}" in paths
    properties = schema["components"]["schemas"]["QuizQuestionResponse"]["properties"]
    assert set(properties) == {"id", "question", "options"}
    conflict_example = paths["/api/v1/quizzes/{quiz_id}/attempts"]["post"]["responses"]["409"][
        "content"
    ]["application/json"]["example"]
    assert conflict_example["detail"]["code"] == "idempotency_conflict"
