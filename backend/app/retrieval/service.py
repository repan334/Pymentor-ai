from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import Text, and_, cast, func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, DocumentChunk
from app.embeddings.models import (
    DocumentEmbeddingInput,
    EmbeddingAdapter,
    EmbeddingError,
    EmbeddingProfile,
)


class IndexingError(RuntimeError):
    code = "indexing_failed"


class IndexDocumentNotFound(IndexingError):
    code = "document_not_found"


class DocumentNotProcessable(IndexingError):
    code = "document_not_processable"


class IndexChunkLimitExceeded(IndexingError):
    code = "index_chunk_limit_exceeded"


class IndexingInProgress(IndexingError):
    code = "indexing_in_progress"


class IndexingConflict(IndexingError):
    code = "indexing_conflict"


class IndexingDeadlineExceeded(IndexingError):
    code = "indexing_deadline_exceeded"


class SearchInputError(ValueError):
    code = "search_input_invalid"


@dataclass(frozen=True, slots=True)
class IndexStatus:
    document_id: int
    ingestion_status: str
    indexing_status: str
    eligible_for_search: bool
    embedding_profile: str | None
    embedded_chunk_count: int
    chunk_count: int
    indexing_started_at: datetime | None
    indexed_at: datetime | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class IndexResult:
    document_id: int
    indexing_status: str
    indexed_chunk_count: int
    embedding_profile: str
    idempotent: bool


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: int
    document_id: int
    source_name: str
    content: str
    start_char: int
    end_char: int
    page_number: int | None
    metadata: dict[str, Any]
    cosine_distance: float


@dataclass(frozen=True, slots=True)
class SearchResult:
    query: str
    top_k: int
    embedding_profile: str
    results: tuple[SearchHit, ...]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ClaimedChunk:
    id: int
    index: int
    content: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _IndexClaim:
    document_id: int
    token: str
    title: str
    content_checksum: str
    chunks: tuple[_ClaimedChunk, ...]


def _corpus_checksum(chunks: Sequence[DocumentChunk | _ClaimedChunk]) -> str:
    digest = sha256()
    for chunk in chunks:
        index = chunk.chunk_index if isinstance(chunk, DocumentChunk) else chunk.index
        digest.update(f"{index}:{chunk.content_sha256}\n".encode())
    return digest.hexdigest()


def _profile_matches(document: Document, profile: EmbeddingProfile) -> bool:
    return (
        document.embedding_provider == profile.provider
        and document.embedding_model == profile.model
        and document.embedding_dimensions == profile.dimensions
        and document.embedding_input_version == profile.input_version
        and document.embedding_profile == profile.key
    )


class IndexingService:
    def __init__(
        self,
        session: Session,
        adapter: EmbeddingAdapter,
        settings: Settings,
        *,
        monotonic: Any = time.monotonic,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.settings = settings
        self._monotonic = monotonic

    def get_status(self, document_id: int) -> IndexStatus:
        document = self.session.get(Document, document_id)
        if document is None:
            raise IndexDocumentNotFound(document_id)
        chunks = self.session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
        corpus_checksum = _corpus_checksum(chunks) if chunks else None
        embedded_count = sum(
            chunk.embedding is not None and chunk.embedding_content_sha256 == chunk.content_sha256
            for chunk in chunks
        )
        eligible = (
            document.indexing_status == "ready"
            and _profile_matches(document, self.adapter.profile)
            and document.embedding_content_checksum == corpus_checksum
            and embedded_count == len(chunks)
            and bool(chunks)
        )
        return IndexStatus(
            document_id=document.id,
            ingestion_status=document.status,
            indexing_status=document.indexing_status,
            eligible_for_search=eligible,
            embedding_profile=document.embedding_profile,
            embedded_chunk_count=embedded_count,
            chunk_count=len(chunks),
            indexing_started_at=document.indexing_started_at,
            indexed_at=document.indexed_at,
            error_code=document.indexing_error_code,
        )

    def index_document(self, document_id: int) -> IndexResult:
        started = self._monotonic()
        claim_or_result = self._claim(document_id)
        if isinstance(claim_or_result, IndexResult):
            return claim_or_result
        claim = claim_or_result

        vectors: list[list[float]] = []
        try:
            for start in range(0, len(claim.chunks), self.settings.embedding_batch_size):
                if self._monotonic() - started >= self.settings.max_indexing_seconds:
                    raise IndexingDeadlineExceeded(
                        "Indexing exceeded the configured total time limit"
                    )
                batch = claim.chunks[start : start + self.settings.embedding_batch_size]
                vectors.extend(
                    self.adapter.embed_documents(
                        [
                            DocumentEmbeddingInput(content=chunk.content, title=claim.title)
                            for chunk in batch
                        ]
                    )
                )
            if self._monotonic() - started >= self.settings.max_indexing_seconds:
                raise IndexingDeadlineExceeded("Indexing exceeded the configured total time limit")
            return self._finalize(claim, vectors)
        except (EmbeddingError, IndexingError) as exc:
            self._mark_failed(claim.document_id, claim.token, exc.code)
            raise

    def _claim(self, document_id: int) -> _IndexClaim | IndexResult:
        try:
            document = self.session.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if document is None:
                raise IndexDocumentNotFound(document_id)
            chunks = self.session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            if document.status not in {"processed", "ready"} or not chunks:
                raise DocumentNotProcessable(
                    "Document extraction and chunking must be complete before indexing"
                )
            if len(chunks) > self.settings.max_index_chunks:
                raise IndexChunkLimitExceeded(
                    f"Document has {len(chunks)} chunks; "
                    f"maximum is {self.settings.max_index_chunks}"
                )

            content_checksum = _corpus_checksum(chunks)
            vectors_current = all(
                chunk.embedding is not None
                and chunk.embedding_content_sha256 == chunk.content_sha256
                for chunk in chunks
            )
            if (
                document.indexing_status == "ready"
                and _profile_matches(document, self.adapter.profile)
                and document.embedding_content_checksum == content_checksum
                and vectors_current
            ):
                self.session.rollback()
                return IndexResult(
                    document_id=document.id,
                    indexing_status="ready",
                    indexed_chunk_count=len(chunks),
                    embedding_profile=self.adapter.profile.key,
                    idempotent=True,
                )

            now = datetime.now(UTC)
            stale_before = now - timedelta(seconds=self.settings.index_claim_timeout_seconds)
            if (
                document.indexing_status == "indexing"
                and document.indexing_started_at is not None
                and document.indexing_started_at > stale_before
            ):
                self.session.rollback()
                raise IndexingInProgress("Document indexing is already in progress")

            token = str(uuid.uuid4())
            document.indexing_status = "indexing"
            document.indexing_token = token
            document.indexing_started_at = now
            document.indexing_error_code = None
            self.session.commit()
            return _IndexClaim(
                document_id=document.id,
                token=token,
                title=document.source_name,
                content_checksum=content_checksum,
                chunks=tuple(
                    _ClaimedChunk(
                        id=chunk.id,
                        index=chunk.chunk_index,
                        content=chunk.content,
                        content_sha256=chunk.content_sha256,
                    )
                    for chunk in chunks
                ),
            )
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def _finalize(self, claim: _IndexClaim, vectors: Sequence[Sequence[float]]) -> IndexResult:
        if len(vectors) != len(claim.chunks):
            raise IndexingConflict("Embedding count changed before persistence")
        try:
            document = self.session.scalar(
                select(Document).where(Document.id == claim.document_id).with_for_update()
            )
            if document is None or document.indexing_token != claim.token:
                raise IndexingConflict("Indexing claim is no longer current")
            chunks = self.session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == claim.document_id)
                .order_by(DocumentChunk.chunk_index)
                .with_for_update()
            ).all()
            if (
                len(chunks) != len(claim.chunks)
                or _corpus_checksum(chunks) != claim.content_checksum
            ):
                raise IndexingConflict("Document chunks changed during indexing")

            for chunk, claimed, vector in zip(chunks, claim.chunks, vectors, strict=True):
                if chunk.id != claimed.id or chunk.content_sha256 != claimed.content_sha256:
                    raise IndexingConflict("Document chunk identity changed during indexing")
                chunk.embedding = list(vector)
                chunk.embedding_content_sha256 = chunk.content_sha256

            profile = self.adapter.profile
            document.embedding_provider = profile.provider
            document.embedding_model = profile.model
            document.embedding_dimensions = profile.dimensions
            document.embedding_input_version = profile.input_version
            document.embedding_profile = profile.key
            document.embedding_content_checksum = claim.content_checksum
            document.indexing_status = "ready"
            document.indexing_token = None
            document.indexing_started_at = None
            document.indexed_at = datetime.now(UTC)
            document.indexing_error_code = None
            self.session.commit()
            return IndexResult(
                document_id=document.id,
                indexing_status="ready",
                indexed_chunk_count=len(chunks),
                embedding_profile=profile.key,
                idempotent=False,
            )
        except Exception:
            self.session.rollback()
            raise

    def _mark_failed(self, document_id: int, token: str, code: str) -> None:
        try:
            document = self.session.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if document is not None and document.indexing_token == token:
                document.indexing_status = "failed"
                document.indexing_token = None
                document.indexing_started_at = None
                document.indexing_error_code = code
                self.session.commit()
            else:
                self.session.rollback()
        except Exception:
            self.session.rollback()
            raise


class SearchService:
    def __init__(
        self,
        session: Session,
        adapter: EmbeddingAdapter,
        settings: Settings,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.settings = settings

    def search(
        self,
        *,
        query: str,
        top_k: int,
        document_ids: Sequence[int] | None,
    ) -> SearchResult:
        if len(query) > self.settings.max_search_query_characters:
            raise SearchInputError("Query exceeds the configured character limit")
        if document_ids is not None and len(document_ids) > self.settings.max_search_document_ids:
            raise SearchInputError("document_ids exceeds the configured item limit")
        if document_ids is not None and not document_ids:
            return SearchResult(
                query=query,
                top_k=top_k,
                embedding_profile=self.adapter.profile.key,
                results=(),
                reason="document_ids_empty",
            )

        eligible_filter = self._eligible_filter()
        chunk_current = and_(
            DocumentChunk.embedding.is_not(None),
            DocumentChunk.embedding_content_sha256 == DocumentChunk.content_sha256,
        )
        chunk_identity_line = (
            cast(DocumentChunk.chunk_index, Text)
            + literal(":")
            + DocumentChunk.content_sha256
            + literal("\n")
        )
        current_corpus_checksum = func.encode(
            func.sha256(
                func.convert_to(
                    func.string_agg(
                        chunk_identity_line,
                        aggregate_order_by(literal(""), DocumentChunk.chunk_index),
                    ),
                    literal("UTF8"),
                )
            ),
            literal("hex"),
        )
        eligible_query = (
            select(Document.id)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(eligible_filter)
            .group_by(Document.id)
            .having(
                func.bool_and(chunk_current),
                current_corpus_checksum == Document.embedding_content_checksum,
            )
        )
        if document_ids is not None:
            eligible_query = eligible_query.where(Document.id.in_(document_ids))
        eligible_ids = tuple(self.session.scalars(eligible_query).all())
        self.session.rollback()
        if not eligible_ids:
            return SearchResult(
                query=query,
                top_k=top_k,
                embedding_profile=self.adapter.profile.key,
                results=(),
                reason="no_eligible_documents",
            )

        query_vector = self.adapter.embed_query(query)
        distance = DocumentChunk.embedding.cosine_distance(query_vector).label("cosine_distance")
        rows = self.session.execute(
            select(DocumentChunk, Document.source_name, distance)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.id.in_(eligible_ids),
                eligible_filter,
                DocumentChunk.embedding.is_not(None),
                DocumentChunk.embedding_content_sha256 == DocumentChunk.content_sha256,
            )
            .order_by(distance.asc(), DocumentChunk.id.asc())
            .limit(top_k)
        ).all()
        hits = tuple(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                source_name=source_name,
                content=chunk.content,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                page_number=chunk.page_number,
                metadata=dict(chunk.extra_metadata),
                cosine_distance=float(cosine_distance),
            )
            for chunk, source_name, cosine_distance in rows
        )
        self.session.rollback()
        return SearchResult(
            query=query,
            top_k=top_k,
            embedding_profile=self.adapter.profile.key,
            results=hits,
        )

    def _eligible_filter(self) -> Any:
        profile = self.adapter.profile
        return and_(
            Document.indexing_status == "ready",
            Document.embedding_provider == profile.provider,
            Document.embedding_model == profile.model,
            Document.embedding_dimensions == profile.dimensions,
            Document.embedding_input_version == profile.input_version,
            Document.embedding_profile == profile.key,
            Document.embedding_content_checksum.is_not(None),
        )
