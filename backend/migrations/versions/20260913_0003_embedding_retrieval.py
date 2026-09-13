"""Add fixed-profile embeddings and indexing state.

Revision ID: 20260913_0003
Revises: 20260913_0002
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260913_0003"
down_revision: str | Sequence[str] | None = "20260913_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "indexing_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'not_indexed'"),
        ),
    )
    op.add_column("documents", sa.Column("embedding_provider", sa.String(40)))
    op.add_column("documents", sa.Column("embedding_model", sa.String(120)))
    op.add_column("documents", sa.Column("embedding_dimensions", sa.Integer()))
    op.add_column("documents", sa.Column("embedding_input_version", sa.String(80)))
    op.add_column("documents", sa.Column("embedding_profile", sa.String(255)))
    op.add_column("documents", sa.Column("embedding_content_checksum", sa.String(64)))
    op.add_column("documents", sa.Column("indexing_token", sa.String(36)))
    op.add_column("documents", sa.Column("indexing_started_at", sa.DateTime(timezone=True)))
    op.add_column("documents", sa.Column("indexed_at", sa.DateTime(timezone=True)))
    op.add_column("documents", sa.Column("indexing_error_code", sa.String(80)))
    op.create_check_constraint(
        "ck_documents_indexing_status_allowed",
        "documents",
        "indexing_status IN ('not_indexed', 'indexing', 'ready', 'failed')",
    )
    op.create_check_constraint(
        "ck_documents_embedding_dimensions_supported",
        "documents",
        "embedding_dimensions IS NULL OR embedding_dimensions = 768",
    )

    op.add_column("document_chunks", sa.Column("content_sha256", sa.String(64)))
    op.add_column("document_chunks", sa.Column("embedding", Vector(768)))
    op.add_column(
        "document_chunks",
        sa.Column("embedding_content_sha256", sa.String(64)),
    )
    op.execute(
        """
        UPDATE document_chunks
        SET content_sha256 = encode(sha256(convert_to(content, 'UTF8')), 'hex')
        WHERE content_sha256 IS NULL
        """
    )
    op.alter_column("document_chunks", "content_sha256", nullable=False)
    op.create_check_constraint(
        "ck_document_chunks_content_sha256_length",
        "document_chunks",
        "length(content_sha256) = 64",
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_content_sha256_length",
        "document_chunks",
        "embedding_content_sha256 IS NULL OR length(embedding_content_sha256) = 64",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_chunks_embedding_content_sha256_length",
        "document_chunks",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_chunks_content_sha256_length",
        "document_chunks",
        type_="check",
    )
    op.drop_column("document_chunks", "embedding_content_sha256")
    op.drop_column("document_chunks", "embedding")
    op.drop_column("document_chunks", "content_sha256")

    op.drop_constraint(
        "ck_documents_embedding_dimensions_supported",
        "documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_documents_indexing_status_allowed",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "indexing_error_code")
    op.drop_column("documents", "indexed_at")
    op.drop_column("documents", "indexing_started_at")
    op.drop_column("documents", "indexing_token")
    op.drop_column("documents", "embedding_content_checksum")
    op.drop_column("documents", "embedding_profile")
    op.drop_column("documents", "embedding_input_version")
    op.drop_column("documents", "embedding_dimensions")
    op.drop_column("documents", "embedding_model")
    op.drop_column("documents", "embedding_provider")
    op.drop_column("documents", "indexing_status")
