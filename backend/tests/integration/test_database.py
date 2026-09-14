import os
import uuid
from hashlib import sha256

import pytest
from app.db.models import Document, DocumentChunk
from app.db.session import create_database_engine
from sqlalchemy import insert, select, text

EXPECTED_REVISION = "20260914_0005"

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="set RUN_DATABASE_TESTS=1 to test the configured Neon database",
)


def test_neon_connection_uses_ssl() -> None:
    engine = create_database_engine()
    try:
        with engine.connect() as connection:
            database_name = connection.execute(text("SELECT current_database()"))
            database_name = database_name.scalar_one()
            driver_connection = connection.connection.driver_connection
            ssl_enabled = driver_connection.pgconn.ssl_in_use

        assert database_name == "neondb"
        assert ssl_enabled is True
    finally:
        engine.dispose()


def test_pgvector_and_alembic_revision_are_current() -> None:
    engine = create_database_engine(for_migrations=True)
    try:
        with engine.connect() as connection:
            vector_version = connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one()
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

        assert vector_version
        assert revision == EXPECTED_REVISION
    finally:
        engine.dispose()


def test_document_round_trip_rolls_back_without_persisting_test_data() -> None:
    engine = create_database_engine(for_migrations=True)
    document_id = uuid.uuid4().int % 8_000_000_000_000_000_000
    chunk_id = uuid.uuid4().int % 8_000_000_000_000_000_000
    checksum = uuid.uuid4().hex + uuid.uuid4().hex

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    insert(Document).values(
                        id=document_id,
                        source_name="phase-3-isolated-test.txt",
                        source_type="text",
                        checksum_sha256=checksum,
                        extraction_profile="text:utf-8-sig:v1",
                        file_size_bytes=22,
                        reference_text="isolated database test",
                        status="processed",
                        extra_metadata={"test": True},
                    )
                )
                connection.execute(
                    insert(DocumentChunk).values(
                        id=chunk_id,
                        document_id=document_id,
                        chunk_index=0,
                        content="isolated database test",
                        content_sha256=sha256(b"isolated database test").hexdigest(),
                        start_char=0,
                        end_char=22,
                        extra_metadata={"test": True},
                    )
                )
                stored_content = connection.execute(
                    select(DocumentChunk.content).where(DocumentChunk.id == chunk_id)
                ).scalar_one()
                assert stored_content == "isolated database test"
            finally:
                transaction.rollback()

        with engine.connect() as connection:
            persisted = connection.execute(
                select(Document.id).where(Document.id == document_id)
            ).scalar_one_or_none()
        assert persisted is None
    finally:
        engine.dispose()
