from datetime import UTC, datetime

from app.api.dependencies import get_quiz_service
from app.core.config import Settings
from app.factory import create_app
from app.quiz.models import (
    AttemptPage,
    AttemptSummaryView,
    QuizInputError,
    QuizPage,
    QuizSummaryView,
)
from fastapi.testclient import TestClient


class FakeListService:
    def __init__(self) -> None:
        self.quiz_kwargs: dict[str, object] | None = None
        self.attempt_kwargs: dict[str, object] | None = None

    def list_quizzes(self, **kwargs: object) -> QuizPage:
        self.quiz_kwargs = kwargs
        if kwargs.get("topic_id") and kwargs.get("unassigned"):
            raise QuizInputError("conflicting filters")
        now = datetime(2026, 9, 14, tzinfo=UTC)
        return QuizPage(
            items=(
                QuizSummaryView(
                    id=10,
                    topic_id=None if kwargs.get("unassigned") else "python-functions",
                    topic="fungsi Python",
                    question_count=3,
                    created_at=now,
                ),
            ),
            total=1,
            limit=int(kwargs["limit"]),
            offset=int(kwargs["offset"]),
        )

    def list_attempts(self, **kwargs: object) -> AttemptPage:
        self.attempt_kwargs = kwargs
        now = datetime(2026, 9, 14, tzinfo=UTC)
        return AttemptPage(
            items=(
                AttemptSummaryView(
                    id=40,
                    quiz_id=10,
                    correct_count=2,
                    question_count=3,
                    percentage=66.67,
                    created_at=now,
                ),
            ),
            total=1,
            limit=int(kwargs["limit"]),
            offset=int(kwargs["offset"]),
        )


def _client(service: FakeListService) -> TestClient:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_quiz_service] = lambda: service
    return TestClient(app)


def test_list_quizzes_supports_unassigned_filter_without_answer_keys() -> None:
    service = FakeListService()
    response = _client(service).get("/api/v1/quizzes?limit=10&offset=0&unassigned=true")

    assert response.status_code == 200
    assert service.quiz_kwargs == {
        "limit": 10,
        "offset": 0,
        "topic_id": None,
        "unassigned": True,
    }
    assert response.json()["items"] == [
        {
            "id": 10,
            "topic_id": None,
            "topic": "fungsi Python",
            "question_count": 3,
            "created_at": "2026-09-14T00:00:00Z",
        }
    ]
    assert "correct_option_id" not in response.text


def test_list_attempts_is_paginated_summary_and_openapi_documents_both_lists() -> None:
    service = FakeListService()
    with _client(service) as client:
        response = client.get("/api/v1/quiz-attempts?limit=5&offset=0&quiz_id=10")
        schema = client.get("/openapi.json").json()

    assert response.status_code == 200
    assert service.attempt_kwargs == {"limit": 5, "offset": 0, "quiz_id": 10}
    assert response.json()["items"][0]["percentage"] == 66.67
    assert "review" not in response.json()["items"][0]
    assert "get" in schema["paths"]["/api/v1/quizzes"]
    assert "get" in schema["paths"]["/api/v1/quiz-attempts"]


def test_list_quizzes_rejects_conflicting_filters() -> None:
    response = _client(FakeListService()).get(
        "/api/v1/quizzes?topic_id=python-functions&unassigned=true"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "quiz_input_invalid"
