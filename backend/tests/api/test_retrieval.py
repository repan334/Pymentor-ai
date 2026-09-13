from dataclasses import replace
from datetime import UTC, datetime

import pytest
from app.api.dependencies import get_indexing_service, get_search_service
from app.core.config import Settings
from app.factory import create_app
from app.retrieval.service import IndexResult, IndexStatus, SearchHit, SearchResult
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


class FakeIndexingService:
    def index_document(self, document_id: int) -> IndexResult:
        return IndexResult(
            document_id=document_id,
            indexing_status="ready",
            indexed_chunk_count=2,
            embedding_profile="gemini:gemini-embedding-2:768:retrieval-asymmetric-v1",
            idempotent=False,
        )

    def get_status(self, document_id: int) -> IndexStatus:
        return IndexStatus(
            document_id=document_id,
            ingestion_status="processed",
            indexing_status="ready",
            eligible_for_search=True,
            embedding_profile="gemini:gemini-embedding-2:768:retrieval-asymmetric-v1",
            embedded_chunk_count=2,
            chunk_count=2,
            indexing_started_at=None,
            indexed_at=datetime.now(UTC),
            error_code=None,
        )


class FakeSearchService:
    def search(self, *, query: str, top_k: int, document_ids: list[int] | None) -> SearchResult:
        return SearchResult(
            query=query,
            top_k=top_k,
            embedding_profile="gemini:gemini-embedding-2:768:retrieval-asymmetric-v1",
            results=(
                SearchHit(
                    chunk_id=5,
                    document_id=2,
                    source_name="functions.md",
                    content="return value",
                    start_char=10,
                    end_char=22,
                    page_number=None,
                    metadata={"document_id": 2},
                    cosine_distance=0.125,
                ),
            ),
        )


class EmptySearchService(FakeSearchService):
    def search(self, *, query: str, top_k: int, document_ids: list[int] | None) -> SearchResult:
        return replace(
            super().search(query=query, top_k=top_k, document_ids=document_ids),
            results=(),
            reason="document_ids_empty",
        )


class UnavailableSearchService(FakeSearchService):
    def search(self, *, query: str, top_k: int, document_ids: list[int] | None) -> SearchResult:
        raise OperationalError("SELECT vector", {}, Exception("secret connection detail"))


@pytest.fixture
def client() -> TestClient:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_indexing_service] = FakeIndexingService
    app.dependency_overrides[get_search_service] = FakeSearchService
    return TestClient(app)


def test_index_and_status_contracts_are_synchronous(client: TestClient) -> None:
    indexed = client.post("/api/v1/documents/2/index")
    status = client.get("/api/v1/documents/2/index-status")

    assert indexed.status_code == 200
    assert indexed.json()["indexing_status"] == "ready"
    assert indexed.json()["idempotent"] is False
    assert status.status_code == 200
    assert status.json()["eligible_for_search"] is True


def test_search_returns_source_offsets_metadata_and_distance(client: TestClient) -> None:
    response = client.post(
        "/api/v1/search",
        json={"query": "How does return work?", "top_k": 3, "document_ids": [2]},
    )

    assert response.status_code == 200
    hit = response.json()["results"][0]
    assert hit == {
        "chunk_id": 5,
        "document_id": 2,
        "source_name": "functions.md",
        "content": "return value",
        "start_char": 10,
        "end_char": 22,
        "page_number": None,
        "metadata": {"document_id": 2},
        "cosine_distance": 0.125,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "   ", "top_k": 3},
        {"query": "valid", "top_k": 0},
        {"query": "valid", "top_k": 21},
        {"query": "valid", "document_ids": [1, 1]},
        {"query": "valid", "document_ids": [0]},
    ],
)
def test_search_rejects_invalid_contract(payload: dict) -> None:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_search_service] = FakeSearchService

    assert TestClient(app).post("/api/v1/search", json=payload).status_code == 422


def test_explicit_empty_document_ids_remains_empty() -> None:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_search_service] = EmptySearchService

    body = (
        TestClient(app).post("/api/v1/search", json={"query": "return", "document_ids": []}).json()
    )

    assert body["results"] == []
    assert body["reason"] == "document_ids_empty"


def test_database_error_is_safe() -> None:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_search_service] = UnavailableSearchService

    response = TestClient(app).post("/api/v1/search", json={"query": "return"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"
    assert "secret connection detail" not in response.text


def test_retrieval_routes_and_distance_meaning_are_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/documents/{document_id}/index" in schema["paths"]
    assert "/api/v1/documents/{document_id}/index-status" in schema["paths"]
    assert "/api/v1/search" in schema["paths"]
    description = schema["components"]["schemas"]["SearchHitResponse"]["properties"][
        "cosine_distance"
    ]["description"]
    assert "not confidence" in description
