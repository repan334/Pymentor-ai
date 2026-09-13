from app.db.base import Base


def test_initial_schema_contains_relational_document_tables() -> None:
    assert set(Base.metadata.tables) == {"documents", "document_chunks"}


def test_embedding_column_is_deferred_until_dimension_is_configured() -> None:
    columns = Base.metadata.tables["document_chunks"].columns

    assert "embedding" not in columns


def test_document_chunk_has_cascade_foreign_key() -> None:
    table = Base.metadata.tables["document_chunks"]
    foreign_key = next(iter(table.foreign_keys))

    assert foreign_key.target_fullname == "documents.id"
    assert foreign_key.ondelete == "CASCADE"
