from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Document(Base):
    """Persisted source text and metadata for an ingested learning document."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('pdf', 'markdown', 'text')",
            name="source_type_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'ready', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("file_size_bytes >= 0", name="file_size_non_negative"),
        CheckConstraint("length(checksum_sha256) = 64", name="checksum_sha256_length"),
        CheckConstraint(
            "indexing_status IN ('not_indexed', 'indexing', 'ready', 'failed')",
            name="indexing_status_allowed",
        ),
        CheckConstraint(
            "embedding_dimensions IS NULL OR embedding_dimensions = 768",
            name="embedding_dimensions_supported",
        ),
        UniqueConstraint(
            "checksum_sha256",
            "extraction_profile",
            name="uq_documents_checksum_extraction_profile",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    indexing_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_indexed",
        server_default=text("'not_indexed'"),
    )
    embedding_provider: Mapped[str | None] = mapped_column(String(40))
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    embedding_input_version: Mapped[str | None] = mapped_column(String(80))
    embedding_profile: Mapped[str | None] = mapped_column(String(255))
    embedding_content_checksum: Mapped[str | None] = mapped_column(String(64))
    indexing_token: Mapped[str | None] = mapped_column(String(36))
    indexing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexing_error_code: Mapped[str | None] = mapped_column(String(80))

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentChunk(Base):
    """Ordered source text and its optional Phase 5 embedding."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_id_chunk_index",
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint("start_char >= 0", name="start_char_non_negative"),
        CheckConstraint("end_char > start_char", name="valid_character_range"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="page_number_positive"),
        CheckConstraint("length(content_sha256) = 64", name="content_sha256_length"),
        CheckConstraint(
            "embedding_content_sha256 IS NULL OR length(embedding_content_sha256) = 64",
            name="embedding_content_sha256_length",
        ),
        Index("ix_document_chunks_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_content_sha256: Mapped[str | None] = mapped_column(String(64))
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document: Mapped[Document] = relationship(back_populates="chunks")


class Quiz(Base):
    """Immutable generated quiz snapshot; answers stay server-side until submission."""

    __tablename__ = "quizzes"
    __table_args__ = (
        CheckConstraint("question_count BETWEEN 1 AND 5", name="quiz_question_count_range"),
        CheckConstraint("length(btrim(topic)) > 0", name="quiz_topic_not_blank"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    document_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    llm_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    generation_profile: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    questions: Mapped[list["QuizQuestion"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuizQuestion.question_index",
    )
    attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", passive_deletes=True
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "question_index", name="uq_quiz_questions_quiz_index"),
        CheckConstraint("question_index >= 0", name="quiz_question_index_non_negative"),
        CheckConstraint("length(btrim(prompt)) > 0", name="quiz_question_prompt_not_blank"),
        CheckConstraint(
            "length(btrim(explanation)) > 0", name="quiz_question_explanation_not_blank"
        ),
        Index("ix_quiz_questions_quiz_id", "quiz_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    quiz_id: Mapped[int] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    quiz: Mapped[Quiz] = relationship(back_populates="questions")
    options: Mapped[list["QuizOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuizOption.option_index",
    )
    sources: Mapped[list["QuizQuestionSource"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuizQuestionSource.reference_id",
    )


class QuizOption(Base):
    __tablename__ = "quiz_options"
    __table_args__ = (
        UniqueConstraint("question_id", "option_index", name="uq_quiz_options_question_index"),
        CheckConstraint("option_index BETWEEN 0 AND 3", name="quiz_option_index_range"),
        CheckConstraint("length(btrim(text)) > 0", name="quiz_option_text_not_blank"),
        Index(
            "uq_quiz_options_one_correct",
            "question_id",
            unique=True,
            postgresql_where=text("is_correct"),
        ),
        Index("ix_quiz_options_question_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False
    )
    option_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)

    question: Mapped[QuizQuestion] = relationship(back_populates="options")


class QuizQuestionSource(Base):
    __tablename__ = "quiz_question_sources"
    __table_args__ = (
        UniqueConstraint(
            "question_id", "reference_id", name="uq_quiz_question_sources_question_reference"
        ),
        UniqueConstraint("question_id", "chunk_id", name="uq_quiz_question_sources_question_chunk"),
        CheckConstraint("start_char >= 0", name="quiz_source_start_char_non_negative"),
        CheckConstraint("end_char > start_char", name="quiz_source_valid_character_range"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="quiz_source_page_positive"),
        Index("ix_quiz_question_sources_question_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False
    )
    reference_id: Mapped[str] = mapped_column(String(16), nullable=False)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    question: Mapped[QuizQuestion] = relationship(back_populates="sources")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        UniqueConstraint("quiz_id", "idempotency_key", name="uq_quiz_attempts_quiz_key"),
        CheckConstraint("correct_count >= 0", name="quiz_attempt_correct_non_negative"),
        CheckConstraint("total_questions > 0", name="quiz_attempt_total_positive"),
        CheckConstraint(
            "correct_count <= total_questions", name="quiz_attempt_correct_not_over_total"
        ),
        CheckConstraint(
            "percentage >= 0 AND percentage <= 100", name="quiz_attempt_percentage_range"
        ),
        CheckConstraint("length(payload_sha256) = 64", name="quiz_attempt_payload_hash_length"),
        Index("ix_quiz_attempts_quiz_id", "quiz_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    quiz_id: Mapped[int] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    quiz: Mapped[Quiz] = relationship(back_populates="attempts")
    answers: Mapped[list["QuizAttemptAnswer"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class QuizAttemptAnswer(Base):
    __tablename__ = "quiz_attempt_answers"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "question_id", name="uq_quiz_attempt_answers_attempt_question"
        ),
        Index("ix_quiz_attempt_answers_attempt_id", "attempt_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False
    )
    selected_option_id: Mapped[int] = mapped_column(
        ForeignKey("quiz_options.id", ondelete="RESTRICT"), nullable=False
    )
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)

    attempt: Mapped[QuizAttempt] = relationship(back_populates="answers")
