from datetime import UTC, datetime
from typing import Any

from app.api.dependencies import get_progress_service
from app.core.config import Settings
from app.factory import create_app
from app.progress.models import (
    QuizTopicAssignment,
    TopicConflict,
    TopicNotFound,
    TopicPage,
    TopicProgress,
    TopicView,
)
from fastapi.testclient import TestClient


def _topic(*, assigned: int = 0) -> TopicView:
    now = datetime(2026, 9, 14, tzinfo=UTC)
    return TopicView(
        id="python-functions",
        display_name="Fungsi Python",
        description="Latihan fungsi",
        created_at=now,
        updated_at=now,
        legacy_quizzes_assigned=assigned,
    )


class FakeProgressService:
    def __init__(self) -> None:
        self.create_result: TopicView | Exception = _topic(assigned=1)
        self.get_result: TopicView | Exception = _topic()
        self.assign_result: QuizTopicAssignment | Exception = QuizTopicAssignment(
            quiz_id=10,
            topic_id="python-functions",
            previous_topic_id=None,
            changed=True,
        )
        self.progress_result: TopicProgress | Exception = TopicProgress(
            topic_id="python-functions",
            topic_name="Fungsi Python",
            score=66.67,
            counted_questions=6,
            counted_quizzes=2,
            recommendation="practice_more",
            message="Lanjutkan latihan.",
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_topic(self, **kwargs: Any) -> TopicView:
        self.calls.append(("create", kwargs))
        if isinstance(self.create_result, Exception):
            raise self.create_result
        return self.create_result

    def list_topics(self, **kwargs: Any) -> TopicPage:
        return TopicPage(items=(_topic(),), total=1, **kwargs)

    def get_topic(self, topic_id: str) -> TopicView:
        if isinstance(self.get_result, Exception):
            raise self.get_result
        return self.get_result

    def assign_quiz(self, **kwargs: Any) -> QuizTopicAssignment:
        self.calls.append(("assign", kwargs))
        if isinstance(self.assign_result, Exception):
            raise self.assign_result
        return self.assign_result

    def get_progress(self, topic_id: str) -> TopicProgress:
        if isinstance(self.progress_result, Exception):
            raise self.progress_result
        return self.progress_result


def _client(service: FakeProgressService) -> TestClient:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_progress_service] = lambda: service
    return TestClient(app)


def test_topic_management_assignment_and_progress_contracts() -> None:
    service = FakeProgressService()
    with _client(service) as client:
        created = client.post(
            "/api/v1/topics",
            json={
                "id": "python-functions",
                "display_name": "Fungsi Python",
                "description": "Latihan fungsi",
            },
        )
        listed = client.get("/api/v1/topics?limit=10&offset=0")
        fetched = client.get("/api/v1/topics/python-functions")
        assigned = client.put("/api/v1/quizzes/10/topic", json={"topic_id": "python-functions"})
        progress = client.get("/api/v1/topics/python-functions/progress")

    assert created.status_code == 201
    assert created.json()["legacy_quizzes_assigned"] == 1
    assert listed.json()["total"] == 1
    assert fetched.json()["id"] == "python-functions"
    assert assigned.json() == {
        "quiz_id": 10,
        "topic_id": "python-functions",
        "previous_topic_id": None,
        "changed": True,
    }
    assert progress.json()["score"] == 66.67
    assert progress.json()["recommendation"] == "practice_more"


def test_invalid_ids_conflicts_not_found_and_openapi() -> None:
    service = FakeProgressService()
    service.create_result = TopicConflict("duplicate")
    conflict = _client(service).post(
        "/api/v1/topics", json={"id": "python-functions", "display_name": "Functions"}
    )
    invalid = _client(FakeProgressService()).post(
        "/api/v1/topics", json={"id": "Invalid ID", "display_name": "Functions"}
    )
    missing_service = FakeProgressService()
    missing_service.progress_result = TopicNotFound("missing")
    missing = _client(missing_service).get("/api/v1/topics/missing/progress")
    with _client(FakeProgressService()) as client:
        schema = client.get("/openapi.json").json()

    assert conflict.status_code == 409
    assert invalid.status_code == 422
    assert missing.status_code == 404
    for path in (
        "/api/v1/topics",
        "/api/v1/topics/{topic_id}",
        "/api/v1/topics/{topic_id}/progress",
        "/api/v1/quizzes/{quiz_id}/topic",
    ):
        assert path in schema["paths"]
