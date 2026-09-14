"""Add stable topics for derived quiz progress.

Revision ID: 20260914_0005
Revises: 20260914_0004
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0005"
down_revision: str | Sequence[str] | None = "20260914_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("normalized_name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "id ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'",
            name="topic_id_slug_format",
        ),
        sa.CheckConstraint("length(btrim(id)) > 0", name="topic_id_not_blank"),
        sa.CheckConstraint("length(btrim(display_name)) > 0", name="topic_name_not_blank"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topics")),
        sa.UniqueConstraint("normalized_name", name="uq_topics_normalized_name"),
    )
    op.add_column("quizzes", sa.Column("topic_id", sa.String(64), nullable=True))
    op.create_foreign_key(
        op.f("fk_quizzes_topic_id_topics"),
        "quizzes",
        "topics",
        ["topic_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_quizzes_topic_id"), "quizzes", ["topic_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_quizzes_topic_id"), table_name="quizzes")
    op.drop_constraint(op.f("fk_quizzes_topic_id_topics"), "quizzes", type_="foreignkey")
    op.drop_column("quizzes", "topic_id")
    op.drop_table("topics")
