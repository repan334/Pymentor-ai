"""Add persistent ingestion identity and source text.

Revision ID: 20260913_0002
Revises: 20260913_0001
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0002"
down_revision: str | Sequence[str] | None = "20260913_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("extraction_profile", sa.String(80), nullable=True))
    op.add_column("documents", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("reference_text", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE documents
        SET extraction_profile = 'legacy:' || source_type || chr(58) || 'v1',
            file_size_bytes = 0,
            reference_text = ''
        WHERE extraction_profile IS NULL
           OR file_size_bytes IS NULL
           OR reference_text IS NULL
        """
    )

    op.alter_column("documents", "extraction_profile", nullable=False)
    op.alter_column("documents", "file_size_bytes", nullable=False)
    op.alter_column("documents", "reference_text", nullable=False)

    op.drop_constraint("ck_documents_status_allowed", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_status_allowed",
        "documents",
        "status IN ('pending', 'processing', 'processed', 'ready', 'failed')",
    )
    op.create_check_constraint(
        "ck_documents_file_size_non_negative",
        "documents",
        "file_size_bytes >= 0",
    )
    op.create_check_constraint(
        "ck_documents_checksum_sha256_length",
        "documents",
        "length(checksum_sha256) = 64",
    )

    op.drop_constraint("uq_documents_checksum_sha256", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_documents_checksum_extraction_profile",
        "documents",
        ["checksum_sha256", "extraction_profile"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_documents_checksum_extraction_profile",
        "documents",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_documents_checksum_sha256",
        "documents",
        ["checksum_sha256"],
    )

    op.drop_constraint("ck_documents_checksum_sha256_length", "documents", type_="check")
    op.drop_constraint("ck_documents_file_size_non_negative", "documents", type_="check")
    op.drop_constraint("ck_documents_status_allowed", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_status_allowed",
        "documents",
        "status IN ('pending', 'processing', 'ready', 'failed')",
    )

    op.drop_column("documents", "reference_text")
    op.drop_column("documents", "file_size_bytes")
    op.drop_column("documents", "extraction_profile")
