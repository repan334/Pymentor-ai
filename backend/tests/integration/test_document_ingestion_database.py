import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest
from app.db.models import Document, DocumentChunk
from app.db.session import create_database_engine
from app.documents.service import DocumentService
from app.ingestion.models import ExtractedDocument, PreparedChunk, PreparedDocument
from app.ingestion.pipeline import prepare_document
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="set RUN_DATABASE_TESTS=1 to test the configured Neon database",
)


def _prepared_document(token: str) -> PreparedDocument:
    return prepare_document(
        token.encode("utf-8"),
        filename="phase-4-integration.txt",
        max_pdf_pages=10,
        max_characters=10_000,
        chunk_size=8,
        chunk_overlap=2,
    )


def test_postgres_concurrent_deduplication_returns_one_document() -> None:
    engine = create_database_engine()
    prepared = _prepared_document(f"phase-4-concurrent-{uuid.uuid4().hex}")
    identity = (
        prepared.extracted.checksum_sha256,
        prepared.extracted.extraction_profile,
    )

    def ingest_once() -> tuple[int, bool]:
        with Session(engine, expire_on_commit=False) as session:
            result = DocumentService(session).ingest(prepared)
            return result.document.id, result.duplicate

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: ingest_once(), range(4)))

        document_ids = {document_id for document_id, _ in results}
        assert len(document_ids) == 1
        assert sum(not duplicate for _, duplicate in results) == 1

        with Session(engine) as session:
            document_count = session.scalar(
                select(func.count(Document.id)).where(
                    Document.checksum_sha256 == identity[0],
                    Document.extraction_profile == identity[1],
                )
            )
            chunk_count = session.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.document_id == next(iter(document_ids))
                )
            )
        assert document_count == 1
        assert chunk_count == len(prepared.chunks)
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(Document).where(
                    Document.checksum_sha256 == identity[0],
                    Document.extraction_profile == identity[1],
                )
            )
        engine.dispose()


def test_postgres_failed_chunk_constraint_rolls_back_document_atomically() -> None:
    engine = create_database_engine()
    token = f"phase-4-atomic-{uuid.uuid4().hex}"
    checksum = sha256(token.encode()).hexdigest()
    prepared = PreparedDocument(
        extracted=ExtractedDocument(
            source_name="phase-4-invalid.txt",
            source_type="text",
            extraction_profile="text:utf-8-sig:v1",
            checksum_sha256=checksum,
            file_size_bytes=len(token),
            reference_text=token,
        ),
        chunks=(
            PreparedChunk(
                index=0,
                content=" ",
                start_char=0,
                end_char=1,
                page_number=None,
                metadata={"test": True},
            ),
        ),
    )

    try:
        with Session(engine) as session:
            with pytest.raises(IntegrityError):
                DocumentService(session).ingest(prepared)

        with Session(engine) as verification_session:
            stored = verification_session.scalar(
                select(Document.id).where(
                    Document.checksum_sha256 == checksum,
                    Document.extraction_profile == "text:utf-8-sig:v1",
                )
            )
        assert stored is None
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Document).where(Document.checksum_sha256 == checksum))
        engine.dispose()
