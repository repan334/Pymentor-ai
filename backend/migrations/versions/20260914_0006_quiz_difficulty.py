"""Add validated difficulty levels to generated quizzes.

Revision ID: 20260914_0006
Revises: 20260914_0005
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0006"
down_revision: str | Sequence[str] | None = "20260914_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("quizzes", sa.Column("difficulty", sa.String(16), nullable=True))
    op.create_check_constraint(
        "quiz_difficulty_valid",
        "quizzes",
        "difficulty IS NULL OR difficulty IN ('basic', 'intermediate', 'advanced')",
    )


def downgrade() -> None:
    op.drop_constraint("quiz_difficulty_valid", "quizzes", type_="check")
    op.drop_column("quizzes", "difficulty")
