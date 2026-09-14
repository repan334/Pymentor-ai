from app.db.base import Base


def test_schema_contains_document_and_quiz_snapshot_tables() -> None:
    assert set(Base.metadata.tables) == {
        "documents",
        "document_chunks",
        "topics",
        "quizzes",
        "quiz_questions",
        "quiz_options",
        "quiz_question_sources",
        "quiz_attempts",
        "quiz_attempt_answers",
    }


def test_embedding_column_uses_verified_phase_5_dimension() -> None:
    columns = Base.metadata.tables["document_chunks"].columns

    assert str(columns["embedding"].type) == "VECTOR(768)"
    assert "content_sha256" in columns


def test_document_model_tracks_indexing_separately_from_ingestion() -> None:
    columns = Base.metadata.tables["documents"].columns

    assert {
        "indexing_status",
        "embedding_provider",
        "embedding_model",
        "embedding_dimensions",
        "embedding_input_version",
        "embedding_profile",
        "embedding_content_checksum",
        "indexing_token",
        "indexing_started_at",
        "indexed_at",
        "indexing_error_code",
    } <= set(columns.keys())


def test_document_model_persists_phase_4_source_and_deduplication_fields() -> None:
    table = Base.metadata.tables["documents"]

    assert {"reference_text", "file_size_bytes", "extraction_profile"} <= set(table.columns.keys())
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("checksum_sha256", "extraction_profile") in unique_columns


def test_document_chunk_has_cascade_foreign_key() -> None:
    table = Base.metadata.tables["document_chunks"]
    foreign_key = next(iter(table.foreign_keys))

    assert foreign_key.target_fullname == "documents.id"
    assert foreign_key.ondelete == "CASCADE"


def test_quiz_attempt_idempotency_and_single_correct_option_are_database_enforced() -> None:
    attempts = Base.metadata.tables["quiz_attempts"]
    options = Base.metadata.tables["quiz_options"]

    attempt_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in attempts.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("quiz_id", "idempotency_key") in attempt_unique_columns
    one_correct = next(
        index for index in options.indexes if index.name == "uq_quiz_options_one_correct"
    )
    assert one_correct.unique is True
    assert one_correct.dialect_options["postgresql"]["where"] is not None
