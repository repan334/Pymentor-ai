from app.db.base import Base


def test_initial_schema_contains_relational_document_tables() -> None:
    assert set(Base.metadata.tables) == {"documents", "document_chunks"}


def test_embedding_column_is_deferred_until_dimension_is_configured() -> None:
    columns = Base.metadata.tables["document_chunks"].columns

    assert "embedding" not in columns


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
