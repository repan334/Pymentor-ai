from __future__ import annotations

from app.api.dependencies import get_document_service
from app.core.config import Settings
from app.factory import create_app
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


class DatabaseDownDocumentService:
    def ingest(self, prepared: object) -> None:
        raise OperationalError("simulated", None, None)


def _client() -> TestClient:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    return TestClient(create_app(settings))


def test_oversized_json_body_is_rejected_with_413_before_routing() -> None:
    body = '{"question": "' + "A" * (1024 * 1024 + 64) + '"}'
    with _client() as client:
        response = client.post(
            "/api/v1/chat",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "json_body_too_large"


def test_small_json_body_reaches_route_validation() -> None:
    with _client() as client:
        response = client.post("/api/v1/chat", json={"question": "", "top_k": 4})

    # 422 route validation (not the middleware 413) proves the body passed through.
    assert response.status_code == 422
    assert "json_body_too_large" not in response.text


def test_oversized_json_body_on_put_route_is_rejected() -> None:
    body = '{"topic_id": "' + "A" * (1024 * 1024 + 64) + '"}'
    with _client() as client:
        response = client.put(
            "/api/v1/quizzes/1/topic",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "json_body_too_large"


def test_multipart_documents_route_is_excluded_from_json_limit() -> None:
    # The JSON limit must not cap multipart uploads; the dedicated multipart
    # middleware keeps its own larger limit. A tiny upload reaching the route
    # (503 from the simulated-down database) proves the exclusion worked.
    app = create_app(
        Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    )
    app.dependency_overrides[get_document_service] = lambda: DatabaseDownDocumentService()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("kecil.txt", b"materi kecil", "text/plain")},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"
