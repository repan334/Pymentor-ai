from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk
from app.ingestion.models import PreparedDocument


class DocumentNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentView:
    id: int
    source_name: str
    source_type: str
    file_size_bytes: int
    checksum_sha256: str
    extraction_profile: str
    status: str
    character_count: int
    chunk_count: int
    reference_text: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    indexing_status: str = "not_indexed"


@dataclass(frozen=True, slots=True)
class ChunkView:
    id: int
    document_id: int
    chunk_index: int
    content: str
    start_char: int
    end_char: int
    page_number: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DocumentPage:
    items: tuple[DocumentView, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class ChunkPage:
    items: tuple[ChunkView, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document: DocumentView
    duplicate: bool


def _document_query() -> Select[tuple[Document, int]]:
    chunk_count = (
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    return select(Document, chunk_count.label("chunk_count"))


def _as_document_view(document: Document, chunk_count: int) -> DocumentView:
    return DocumentView(
        id=document.id,
        source_name=document.source_name,
        source_type=document.source_type,
        file_size_bytes=document.file_size_bytes,
        checksum_sha256=document.checksum_sha256,
        extraction_profile=document.extraction_profile,
        status=document.status,
        indexing_status=document.indexing_status,
        character_count=len(document.reference_text),
        chunk_count=chunk_count,
        reference_text=document.reference_text,
        metadata=dict(document.extra_metadata),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


class DocumentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _find_by_identity(self, prepared: PreparedDocument) -> DocumentView | None:
        row = self.session.execute(
            _document_query().where(
                Document.checksum_sha256 == prepared.extracted.checksum_sha256,
                Document.extraction_profile == prepared.extracted.extraction_profile,
            )
        ).one_or_none()
        if row is None:
            return None
        return _as_document_view(row[0], row[1])

    def ingest(self, prepared: PreparedDocument) -> IngestionResult:
        existing = self._find_by_identity(prepared)
        if existing is not None:
            self.session.rollback()
            return IngestionResult(document=existing, duplicate=True)

        source = prepared.extracted
        document = Document(
            source_name=source.source_name,
            source_type=source.source_type,
            checksum_sha256=source.checksum_sha256,
            extraction_profile=source.extraction_profile,
            file_size_bytes=source.file_size_bytes,
            reference_text=source.reference_text,
            status="processed",
            extra_metadata=source.metadata,
        )

        try:
            self.session.add(document)
            self.session.flush()
            self.session.add_all(
                [
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=chunk.index,
                        content=chunk.content,
                        content_sha256=sha256(chunk.content.encode("utf-8")).hexdigest(),
                        start_char=chunk.start_char,
                        end_char=chunk.end_char,
                        page_number=chunk.page_number,
                        extra_metadata={**chunk.metadata, "document_id": document.id},
                    )
                    for chunk in prepared.chunks
                ]
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self._find_by_identity(prepared)
            if existing is not None:
                self.session.rollback()
                return IngestionResult(document=existing, duplicate=True)
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

        return IngestionResult(
            document=_as_document_view(document, len(prepared.chunks)),
            duplicate=False,
        )

    def list_documents(self, *, limit: int, offset: int) -> DocumentPage:
        total = self.session.scalar(select(func.count(Document.id))) or 0
        rows = self.session.execute(
            _document_query().order_by(Document.id.desc()).limit(limit).offset(offset)
        ).all()
        return DocumentPage(
            items=tuple(_as_document_view(document, count) for document, count in rows),
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_document(self, document_id: int) -> DocumentView:
        row = self.session.execute(
            _document_query().where(Document.id == document_id)
        ).one_or_none()
        if row is None:
            raise DocumentNotFound(document_id)
        return _as_document_view(row[0], row[1])

    def list_chunks(self, document_id: int, *, limit: int, offset: int) -> ChunkPage:
        if self.session.scalar(select(Document.id).where(Document.id == document_id)) is None:
            raise DocumentNotFound(document_id)

        total = (
            self.session.scalar(
                select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
            )
            or 0
        )
        chunks = self.session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
            .offset(offset)
        ).all()
        return ChunkPage(
            items=tuple(
                ChunkView(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    page_number=chunk.page_number,
                    metadata=dict(chunk.extra_metadata),
                )
                for chunk in chunks
            ),
            total=total,
            limit=limit,
            offset=offset,
        )
