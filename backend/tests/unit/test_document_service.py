from unittest.mock import MagicMock

import pytest
from app.documents.service import DocumentService
from app.ingestion.pipeline import prepare_document


def test_unexpected_transaction_failure_rolls_back() -> None:
    session = MagicMock()
    session.execute.return_value.one_or_none.return_value = None
    session.commit.side_effect = RuntimeError("forced test failure")
    prepared = prepare_document(
        b"transactional text",
        filename="lesson.txt",
        max_pdf_pages=10,
        max_characters=100,
        chunk_size=100,
        chunk_overlap=0,
    )

    with pytest.raises(RuntimeError, match="forced test failure"):
        DocumentService(session).ingest(prepared)

    session.rollback.assert_called_once_with()
