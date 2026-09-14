"""Add immutable quiz snapshots and scored attempts.

Revision ID: 20260914_0004
Revises: 20260913_0003
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_0004"
down_revision: str | Sequence[str] | None = "20260913_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quizzes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_provider", sa.String(40), nullable=False),
        sa.Column("llm_model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("generation_profile", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("question_count BETWEEN 1 AND 5", name="quiz_question_count_range"),
        sa.CheckConstraint("length(btrim(topic)) > 0", name="quiz_topic_not_blank"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quizzes")),
    )
    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("quiz_id", sa.BigInteger(), nullable=False),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(explanation)) > 0", name="quiz_question_explanation_not_blank"
        ),
        sa.CheckConstraint("question_index >= 0", name="quiz_question_index_non_negative"),
        sa.CheckConstraint("length(btrim(prompt)) > 0", name="quiz_question_prompt_not_blank"),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            ["quizzes.id"],
            name=op.f("fk_quiz_questions_quiz_id_quizzes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_questions")),
        sa.UniqueConstraint("quiz_id", "question_index", name="uq_quiz_questions_quiz_index"),
    )
    op.create_index("ix_quiz_questions_quiz_id", "quiz_questions", ["quiz_id"])
    op.create_table(
        "quiz_options",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.CheckConstraint("option_index BETWEEN 0 AND 3", name="quiz_option_index_range"),
        sa.CheckConstraint("length(btrim(text)) > 0", name="quiz_option_text_not_blank"),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["quiz_questions.id"],
            name=op.f("fk_quiz_options_question_id_quiz_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_options")),
        sa.UniqueConstraint("question_id", "option_index", name="uq_quiz_options_question_index"),
    )
    op.create_index("ix_quiz_options_question_id", "quiz_options", ["question_id"])
    op.create_index(
        "uq_quiz_options_one_correct",
        "quiz_options",
        ["question_id"],
        unique=True,
        postgresql_where=sa.text("is_correct"),
    )
    op.create_table(
        "quiz_question_sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("reference_id", sa.String(16), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_id", sa.BigInteger(), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("start_char >= 0", name="quiz_source_start_char_non_negative"),
        sa.CheckConstraint("end_char > start_char", name="quiz_source_valid_character_range"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0", name="quiz_source_page_positive"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["quiz_questions.id"],
            name=op.f("fk_quiz_question_sources_question_id_quiz_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_question_sources")),
        sa.UniqueConstraint(
            "question_id", "chunk_id", name="uq_quiz_question_sources_question_chunk"
        ),
        sa.UniqueConstraint(
            "question_id", "reference_id", name="uq_quiz_question_sources_question_reference"
        ),
    )
    op.create_index(
        "ix_quiz_question_sources_question_id", "quiz_question_sources", ["question_id"]
    )
    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("quiz_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("correct_count >= 0", name="quiz_attempt_correct_non_negative"),
        sa.CheckConstraint(
            "correct_count <= total_questions", name="quiz_attempt_correct_not_over_total"
        ),
        sa.CheckConstraint("length(payload_sha256) = 64", name="quiz_attempt_payload_hash_length"),
        sa.CheckConstraint(
            "percentage >= 0 AND percentage <= 100", name="quiz_attempt_percentage_range"
        ),
        sa.CheckConstraint("total_questions > 0", name="quiz_attempt_total_positive"),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            ["quizzes.id"],
            name=op.f("fk_quiz_attempts_quiz_id_quizzes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempts")),
        sa.UniqueConstraint("quiz_id", "idempotency_key", name="uq_quiz_attempts_quiz_key"),
    )
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"])
    op.create_table(
        "quiz_attempt_answers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("selected_option_id", sa.BigInteger(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["quiz_attempts.id"],
            name=op.f("fk_quiz_attempt_answers_attempt_id_quiz_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["quiz_questions.id"],
            name=op.f("fk_quiz_attempt_answers_question_id_quiz_questions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selected_option_id"],
            ["quiz_options.id"],
            name=op.f("fk_quiz_attempt_answers_selected_option_id_quiz_options"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempt_answers")),
        sa.UniqueConstraint(
            "attempt_id", "question_id", name="uq_quiz_attempt_answers_attempt_question"
        ),
    )
    op.create_index("ix_quiz_attempt_answers_attempt_id", "quiz_attempt_answers", ["attempt_id"])


def downgrade() -> None:
    op.drop_table("quiz_attempt_answers")
    op.drop_table("quiz_attempts")
    op.drop_table("quiz_question_sources")
    op.drop_table("quiz_options")
    op.drop_table("quiz_questions")
    op.drop_table("quizzes")
