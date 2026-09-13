import os
import uuid
from collections.abc import Iterator
from hashlib import sha256

import pytest
from app.core.config import Settings
from app.db.models import Document
from app.db.session import create_database_engine, get_session
from app.factory import create_app
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_RETRIEVAL_TESTS") != "1",
    reason="set RUN_LIVE_RETRIEVAL_TESTS=1 for Gemini + Neon API integration",
)


def test_live_api_upload_index_idempotency_and_search() -> None:
    token = uuid.uuid4().hex
    content = f"Phase 5 fixture {token}. A Python function returns a result with return."
    checksum = sha256(content.encode()).hexdigest()
    settings = Settings().model_copy(update={"embedding_max_attempts": 1})
    engine = create_database_engine(settings)
    session_factory = sessionmaker(engine, expire_on_commit=False)

    def test_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app = create_app(settings)
    app.dependency_overrides[get_session] = test_session
    try:
        with TestClient(app) as client:
            upload = client.post(
                "/api/v1/documents",
                files={"file": ("phase-5-live.txt", content.encode(), "text/plain")},
            )
            duplicate = client.post(
                "/api/v1/documents",
                files={"file": ("renamed.txt", content.encode(), "text/plain")},
            )
            document_id = upload.json()["id"]
            indexed = client.post(f"/api/v1/documents/{document_id}/index")
            repeated = client.post(f"/api/v1/documents/{document_id}/index")
            search = client.post(
                "/api/v1/search",
                json={
                    "query": "How does a Python function return a result?",
                    "top_k": 3,
                    "document_ids": [document_id],
                },
            )

        assert upload.status_code == 201
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == document_id
        assert indexed.status_code == 200
        assert indexed.json()["idempotent"] is False
        assert repeated.status_code == 200
        assert repeated.json()["idempotent"] is True
        assert search.status_code == 200
        assert search.json()["results"][0]["document_id"] == document_id
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Document).where(Document.checksum_sha256 == checksum))
        engine.dispose()
