from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import pytest
from app.core.config import Settings
from app.db.models import Document, DocumentChunk
from app.db.session import create_database_engine
from app.embeddings.models import DocumentEmbeddingInput, EmbeddingProfile
from app.retrieval.service import (
    IndexingConflict,
    IndexingInProgress,
    IndexingService,
    SearchService,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="set RUN_DATABASE_TESTS=1 to test the configured Neon database",
    ),
]


PROFILE = EmbeddingProfile(
    provider="gemini",
    model="gemini-embedding-2",
    dimensions=768,
    input_version="retrieval-asymmetric-v1",
)


def _vector(first: float, second: float) -> list[float]:
    return [first, second, *([0.0] * 766)]


class DeterministicAdapter:
    profile = PROFILE

    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, inputs: list[DocumentEmbeddingInput]) -> list[list[float]]:
        self.document_calls += 1
        return [
            _vector(1.0, 0.0) if "return" in value.content else _vector(0.0, 1.0)
            for value in inputs
        ]

    def embed_query(self, query: str) -> list[float]:
        self.query_calls += 1
        return _vector(1.0, 0.0)


class BlockingAdapter(DeterministicAdapter):
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.entered = entered
        self.release = release

    def embed_documents(self, inputs: list[DocumentEmbeddingInput]) -> list[list[float]]:
        self.entered.set()
        assert self.release.wait(15)
        return super().embed_documents(inputs)


class IncompleteAdapter(DeterministicAdapter):
    def embed_documents(self, inputs: list[DocumentEmbeddingInput]) -> list[list[float]]:
        return []


def _settings() -> Settings:
    return Settings(_env_file=None, embedding_batch_size=16, index_claim_timeout_seconds=2)


def _create_document(session: Session, token: str, contents: list[str]) -> Document:
    reference = "\n".join(contents)
    document = Document(
        source_name=f"phase-5-{token}.txt",
        source_type="text",
        checksum_sha256=sha256(token.encode()).hexdigest(),
        extraction_profile="text:utf-8-sig:v1",
        file_size_bytes=len(reference.encode()),
        reference_text=reference,
        status="processed",
        indexing_status="not_indexed",
        extra_metadata={"test_token": token},
    )
    session.add(document)
    session.flush()
    start = 0
    for index, content in enumerate(contents):
        content_hash = sha256(content.encode()).hexdigest()
        session.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                content=content,
                content_sha256=content_hash,
                start_char=start,
                end_char=start + len(content),
                extra_metadata={"test_token": token, "document_id": document.id},
            )
        )
        start += len(content) + 1
    session.commit()
    return document


def _cleanup(engine: Any, checksums: list[str]) -> None:
    with engine.begin() as connection:
        connection.execute(delete(Document).where(Document.checksum_sha256.in_(checksums)))


def test_postgres_vector_persistence_idempotency_filter_and_cosine_ranking() -> None:
    engine = create_database_engine()
    token = uuid.uuid4().hex
    checksum = sha256(token.encode()).hexdigest()
    adapter = DeterministicAdapter()
    try:
        with Session(engine, expire_on_commit=False) as session:
            document = _create_document(session, token, ["return a value", "iterate over items"])
            first = IndexingService(session, adapter, _settings()).index_document(document.id)
            second = IndexingService(session, adapter, _settings()).index_document(document.id)

            assert first.idempotent is False
            assert second.idempotent is True
            assert adapter.document_calls == 1

            result = SearchService(session, adapter, _settings()).search(
                query="How is a value returned?",
                top_k=2,
                document_ids=[document.id],
            )
            assert [hit.content for hit in result.results] == [
                "return a value",
                "iterate over items",
            ]
            assert result.results[0].cosine_distance < result.results[1].cosine_distance
            assert adapter.query_calls == 1

            stored = session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            assert all(
                chunk.embedding is not None and len(chunk.embedding) == 768 for chunk in stored
            )

            document.embedding_model = "incompatible-model"
            session.commit()
            empty = SearchService(session, adapter, _settings()).search(
                query="return", top_k=2, document_ids=[document.id]
            )
            assert empty.reason == "no_eligible_documents"
            assert adapter.query_calls == 1
    finally:
        _cleanup(engine, [checksum])
        engine.dispose()


def test_postgres_concurrent_index_claim_allows_only_one_provider_call() -> None:
    engine = create_database_engine()
    token = uuid.uuid4().hex
    checksum = sha256(token.encode()).hexdigest()
    entered = threading.Event()
    release = threading.Event()
    adapter = BlockingAdapter(entered, release)
    try:
        with Session(engine, expire_on_commit=False) as setup_session:
            document_id = _create_document(setup_session, token, ["return once"]).id

        def first_request() -> bool:
            with Session(engine) as session:
                return (
                    IndexingService(session, adapter, _settings())
                    .index_document(document_id)
                    .idempotent
                )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(first_request)
            assert entered.wait(15)
            with Session(engine) as competing_session:
                with pytest.raises(IndexingInProgress):
                    IndexingService(
                        competing_session, DeterministicAdapter(), _settings()
                    ).index_document(document_id)
            release.set()
            assert future.result(timeout=15) is False
        assert adapter.document_calls == 1
    finally:
        release.set()
        _cleanup(engine, [checksum])
        engine.dispose()


def test_postgres_incomplete_result_rolls_back_vectors_and_stale_claim_recovers() -> None:
    engine = create_database_engine()
    token = uuid.uuid4().hex
    checksum = sha256(token.encode()).hexdigest()
    try:
        with Session(engine, expire_on_commit=False) as session:
            document = _create_document(session, token, ["return safely"])
            with pytest.raises(IndexingConflict):
                IndexingService(session, IncompleteAdapter(), _settings()).index_document(
                    document.id
                )

            session.refresh(document)
            chunk = session.scalar(
                select(DocumentChunk).where(DocumentChunk.document_id == document.id)
            )
            assert document.indexing_status == "failed"
            assert chunk is not None and chunk.embedding is None

            document.indexing_status = "indexing"
            document.indexing_token = "abandoned"
            document.indexing_started_at = datetime.now(UTC) - timedelta(minutes=10)
            session.commit()

            recovered = IndexingService(
                session, DeterministicAdapter(), _settings()
            ).index_document(document.id)
            assert recovered.indexing_status == "ready"
    finally:
        _cleanup(engine, [checksum])
        engine.dispose()
