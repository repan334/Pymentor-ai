import pytest
from app.ingestion.errors import (
    EmptyDocument,
    EncryptedPdf,
    ExtractedTextLimitExceeded,
    InvalidPdf,
    InvalidTextEncoding,
    NoUsablePdfText,
    PdfPageLimitExceeded,
    UnsupportedDocumentFormat,
)
from app.ingestion.readers import PDF_PAGE_SEPARATOR, extract_document

from tests.pdf_factory import build_blank_pdf, build_text_pdf


def extract(data: bytes, filename: str, *, pages: int = 10, characters: int = 10_000):
    return extract_document(
        data,
        filename=filename,
        max_pdf_pages=pages,
        max_characters=characters,
    )


@pytest.mark.parametrize(
    ("filename", "source_type"),
    [("lesson.txt", "text"), ("lesson.MD", "markdown")],
)
def test_text_and_markdown_preserve_bom_newlines_fences_and_indentation(
    filename: str,
    source_type: str,
) -> None:
    text = "# Python\r\n\r\n```python\r\nif True:\r\n    print('ok')\r\n```\r\n"
    result = extract(text.encode("utf-8-sig"), filename)

    assert result.source_type == source_type
    assert result.reference_text == text
    assert result.metadata["normalization_applied"] is False
    assert result.file_size_bytes == len(text.encode("utf-8-sig"))


def test_pdf_text_has_document_global_page_offsets() -> None:
    result = extract(build_text_pdf("First page", "Second page"), "lesson.pdf")

    assert result.source_type == "pdf"
    assert len(result.pages) == 2
    assert result.reference_text == (
        result.pages[0].text + PDF_PAGE_SEPARATOR + result.pages[1].text
    )
    for page in result.pages:
        assert result.reference_text[page.start_char : page.end_char] == page.text
    assert result.pages[0].page_number == 1
    assert result.pages[1].page_number == 2


@pytest.mark.parametrize("data", [b"", b" \t\r\n"])
def test_empty_or_whitespace_text_is_rejected(data: bytes) -> None:
    with pytest.raises(EmptyDocument):
        extract(data, "empty.txt")


def test_invalid_utf8_is_rejected() -> None:
    with pytest.raises(InvalidTextEncoding):
        extract(b"\xff\xfe\xfd", "lesson.txt")


def test_unsupported_extension_and_content_mismatch_are_rejected() -> None:
    with pytest.raises(UnsupportedDocumentFormat):
        extract(b"plain text", "lesson.docx")
    with pytest.raises(UnsupportedDocumentFormat):
        extract(build_text_pdf("PDF"), "lesson.txt")
    with pytest.raises(UnsupportedDocumentFormat):
        extract(b"not a pdf", "lesson.pdf")


def test_binary_control_content_is_not_accepted_as_text() -> None:
    with pytest.raises(UnsupportedDocumentFormat):
        extract(b"Python\x00binary", "lesson.md")


def test_corrupt_encrypted_and_textless_pdfs_have_specific_errors() -> None:
    with pytest.raises(InvalidPdf):
        extract(b"%PDF-1.4\nbroken", "broken.pdf")
    with pytest.raises(EncryptedPdf):
        extract(build_blank_pdf(encrypted=True), "protected.pdf")
    with pytest.raises(NoUsablePdfText, match="may require OCR"):
        extract(build_blank_pdf(), "blank.pdf")


def test_pdf_page_and_extracted_character_limits_are_enforced() -> None:
    with pytest.raises(PdfPageLimitExceeded):
        extract(build_text_pdf("one", "two"), "pages.pdf", pages=1)
    with pytest.raises(ExtractedTextLimitExceeded):
        extract(build_text_pdf("too long"), "characters.pdf", characters=3)


def test_filename_is_reduced_to_display_name_without_filesystem_use() -> None:
    result = extract(b"safe", "C:\\untrusted\\lesson.txt")

    assert result.source_name == "lesson.txt"
