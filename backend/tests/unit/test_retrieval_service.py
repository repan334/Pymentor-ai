from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import pytest
from app.core.config import Settings
from app.db.models import Document, DocumentChunk
from app.embeddings.models import (
    DocumentEmbeddingInput,
    EmbeddingProfile,
    EmbeddingTimeoutError,
)
from app.retrieval.service import (
    IndexChunkLimitExceeded,
    IndexingDeadlineExceeded,
    IndexingInProgress,
    IndexingService,
    SearchInputError,
    SearchService,
)


class ScalarRows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, document: Document, chunks: list[DocumentChunk]) -> None:
        self.document = document
        self.chunks = chunks
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, statement: Any) -> Document:
        return self.document

    def scalars(self, statement: Any) -> ScalarRows:
        return ScalarRows(self.chunks)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def in_transaction(self) -> bool:
        return False


class EmptySearchSession:
    def __init__(self) -> None:
        self.queries = 0
        self.rollbacks = 0

    def scalars(self, statement: Any) -> ScalarRows:
        self.queries += 1
        return ScalarRows([])

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeAdapter:
    profile = EmbeddingProfile("gemini", "gemini-embedding-2", 768, "retrieval-asymmetric-v1")

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.document_calls: list[list[DocumentEmbeddingInput]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, inputs: list[DocumentEmbeddingInput]) -> list[list[float]]:
        self.document_calls.append(inputs)
        if self.failure is not None:
            raise self.failure
        return [[1.0, *([0.0] * 767)] for _ in inputs]

    def embed_query(self, query: str) -> list[float]:
        self.query_calls.append(query)
        return [1.0, *([0.0] * 767)]


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, database_url=None, gemini_api_key=None, **overrides)


def _stored_document() -> tuple[Document, list[DocumentChunk]]:
    content = "return 42"
    content_hash = sha256(content.encode()).hexdigest()
    document = Document(
        id=10,
        source_name="lesson.md",
        source_type="markdown",
        checksum_sha256=sha256(b"lesson").hexdigest(),
        extraction_profile="markdown:utf-8-sig:v1",
        file_size_bytes=len(content),
        reference_text=content,
        status="processed",
        indexing_status="not_indexed",
        extra_metadata={},
    )
    chunk = DocumentChunk(
        id=20,
        document_id=10,
        chunk_index=0,
        content=content,
        content_sha256=content_hash,
        start_char=0,
        end_char=len(content),
        extra_metadata={"document_id": 10},
    )
    return document, [chunk]


def test_indexing_maps_one_embedding_to_each_chunk_and_becomes_ready() -> None:
    document, chunks = _stored_document()
    second = DocumentChunk(
        id=21,
        document_id=10,
        chunk_index=1,
        content="next chunk",
        content_sha256=sha256(b"next chunk").hexdigest(),
        start_char=10,
        end_char=20,
        extra_metadata={"document_id": 10},
    )
    chunks.append(second)
    session = FakeSession(document, chunks)
    adapter = FakeAdapter()

    result = IndexingService(session, adapter, _settings(embedding_batch_size=1)).index_document(10)

    assert result.idempotent is False
    assert result.indexed_chunk_count == 2
    assert len(adapter.document_calls) == 2
    assert [call[0].content for call in adapter.document_calls] == ["return 42", "next chunk"]
    assert all(chunk.embedding is not None and len(chunk.embedding) == 768 for chunk in chunks)
    assert document.indexing_status == "ready"
    assert document.embedding_profile == adapter.profile.key
    assert session.commits == 2


def test_ready_matching_index_is_idempotent_without_provider_call() -> None:
    document, chunks = _stored_document()
    adapter = FakeAdapter()
    first = IndexingService(FakeSession(document, chunks), adapter, _settings()).index_document(10)
    second = IndexingService(FakeSession(document, chunks), adapter, _settings()).index_document(10)

    assert first.idempotent is False
    assert second.idempotent is True
    assert len(adapter.document_calls) == 1


def test_fresh_concurrent_claim_is_rejected_without_provider_call() -> None:
    document, chunks = _stored_document()
    document.indexing_status = "indexing"
    document.indexing_started_at = datetime.now(UTC)
    document.indexing_token = "another-request"
    adapter = FakeAdapter()

    with pytest.raises(IndexingInProgress):
        IndexingService(FakeSession(document, chunks), adapter, _settings()).index_document(10)
    assert adapter.document_calls == []


def test_stale_claim_is_recovered() -> None:
    document, chunks = _stored_document()
    document.indexing_status = "indexing"
    document.indexing_started_at = datetime.now(UTC) - timedelta(hours=1)
    document.indexing_token = "dead-process"
    adapter = FakeAdapter()

    result = IndexingService(
        FakeSession(document, chunks), adapter, _settings(index_claim_timeout_seconds=10)
    ).index_document(10)

    assert result.indexing_status == "ready"
    assert document.indexing_token is None


def test_provider_failure_marks_failed_without_partial_vectors() -> None:
    document, chunks = _stored_document()
    adapter = FakeAdapter(failure=EmbeddingTimeoutError("timeout"))

    with pytest.raises(EmbeddingTimeoutError):
        IndexingService(FakeSession(document, chunks), adapter, _settings()).index_document(10)

    assert document.indexing_status == "failed"
    assert document.indexing_error_code == "embedding_timeout"
    assert chunks[0].embedding is None


def test_chunk_limit_rejects_whole_document_before_provider_call() -> None:
    document, chunks = _stored_document()
    chunks.append(
        DocumentChunk(
            id=21,
            document_id=10,
            chunk_index=1,
            content="another",
            content_sha256=sha256(b"another").hexdigest(),
            start_char=10,
            end_char=17,
            extra_metadata={},
        )
    )
    adapter = FakeAdapter()

    with pytest.raises(IndexChunkLimitExceeded):
        IndexingService(
            FakeSession(document, chunks), adapter, _settings(max_index_chunks=1)
        ).index_document(10)
    assert adapter.document_calls == []


def test_total_deadline_marks_failed_before_partial_indexing() -> None:
    document, chunks = _stored_document()
    adapter = FakeAdapter()
    times = iter([0.0, 121.0])

    with pytest.raises(IndexingDeadlineExceeded):
        IndexingService(
            FakeSession(document, chunks),
            adapter,
            _settings(max_indexing_seconds=120),
            monotonic=lambda: next(times),
        ).index_document(10)
    assert adapter.document_calls == []
    assert document.indexing_status == "failed"


def test_empty_document_filter_does_not_embed_query() -> None:
    adapter = FakeAdapter()
    service = SearchService(EmptySearchSession(), adapter, _settings())

    result = service.search(query="return", top_k=3, document_ids=[])

    assert result.reason == "document_ids_empty"
    assert result.results == ()
    assert adapter.query_calls == []


def test_no_eligible_corpus_does_not_embed_query() -> None:
    adapter = FakeAdapter()
    session = EmptySearchSession()
    service = SearchService(session, adapter, _settings())

    result = service.search(query="return", top_k=3, document_ids=None)

    assert result.reason == "no_eligible_documents"
    assert adapter.query_calls == []
    assert session.queries == 1
    assert session.rollbacks == 1


def test_search_enforces_configured_query_and_document_id_limits() -> None:
    adapter = FakeAdapter()
    service = SearchService(
        EmptySearchSession(),
        adapter,
        _settings(max_search_query_characters=5, max_search_document_ids=1),
    )

    with pytest.raises(SearchInputError):
        service.search(query="too long", top_k=3, document_ids=None)
    with pytest.raises(SearchInputError):
        service.search(query="short", top_k=3, document_ids=[1, 2])
    assert adapter.query_calls == []
