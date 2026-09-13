from app.ingestion.pipeline import prepare_document

from tests.pdf_factory import build_text_pdf


def prepare(data: bytes, filename: str, *, chunk_size: int = 8, overlap: int = 2):
    return prepare_document(
        data,
        filename=filename,
        max_pdf_pages=10,
        max_characters=10_000,
        chunk_size=chunk_size,
        chunk_overlap=overlap,
    )


def test_text_chunks_address_persisted_reference_text() -> None:
    result = prepare(b"def f():\r\n    return 42\r\n", "lesson.txt")

    assert [chunk.index for chunk in result.chunks] == list(range(len(result.chunks)))
    for chunk in result.chunks:
        assert result.extracted.reference_text[chunk.start_char : chunk.end_char] == chunk.content
        assert chunk.page_number is None


def test_pdf_chunk_indexes_are_global_while_page_metadata_is_retained() -> None:
    result = prepare(build_text_pdf("abcdefghij", "klmnopqrst"), "lesson.pdf")

    assert [chunk.index for chunk in result.chunks] == list(range(len(result.chunks)))
    assert {chunk.page_number for chunk in result.chunks} == {1, 2}
    for chunk in result.chunks:
        assert result.extracted.reference_text[chunk.start_char : chunk.end_char] == chunk.content
        assert chunk.metadata["page_number"] == chunk.page_number
