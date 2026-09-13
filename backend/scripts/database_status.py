"""Print non-secret database state used to verify the Phase 3 deployment."""

import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import create_database_engine  # noqa: E402


def main() -> None:
    engine = create_database_engine(for_migrations=True)
    try:
        with engine.connect() as connection:
            identity = connection.execute(
                text(
                    """
                    SELECT
                        current_database(),
                        current_schema(),
                        current_setting('server_version')
                    """
                )
            ).one()
            driver_connection = connection.connection.driver_connection
            ssl_enabled = driver_connection.pgconn.ssl_in_use
            tables = connection.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                    """
                )
            ).scalars()
            vector_version = connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()
            revision_table_exists = connection.execute(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            ).scalar_one()
            revision = None
            if revision_table_exists:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            document_count = connection.execute(text("SELECT count(*) FROM documents")).scalar_one()
            chunk_count = connection.execute(
                text("SELECT count(*) FROM document_chunks")
            ).scalar_one()
            document_columns = connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'documents'
                    ORDER BY ordinal_position
                    """
                )
            ).scalars()

        print(f"database={identity[0]}")
        print(f"schema={identity[1]}")
        print(f"postgres={identity[2]}")
        print(f"ssl={ssl_enabled}")
        print(f"public_tables={','.join(tables)}")
        print(f"pgvector={vector_version or 'not installed'}")
        print(f"alembic_revision={revision or 'not initialized'}")
        print(f"documents={document_count}")
        print(f"document_chunks={chunk_count}")
        print(f"document_columns={','.join(document_columns)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
