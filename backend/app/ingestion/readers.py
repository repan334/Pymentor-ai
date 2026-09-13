from __future__ import annotations

from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader
from pypdf import __version__ as pypdf_version
from pypdf.errors import PdfReadError

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
from app.ingestion.models import ExtractedDocument, ExtractedPage

PDF_PAGE_SEPARATOR = "\n\f\n"
_TEXT_PROFILES = {
    ".txt": ("text", "text:utf-8-sig:v1"),
    ".md": ("markdown", "markdown:utf-8-sig:v1"),
}
_PDF_PROFILE = "pdf:pypdf:v1"
_ALLOWED_TEXT_CONTROLS = {"\t", "\n", "\r", "\f"}


def _safe_display_name(filename: str | None) -> str:
    if filename is None:
        raise UnsupportedDocumentFormat("The upload must include a filename")

    name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
    if not name or name in {".", ".."}:
        raise UnsupportedDocumentFormat("The upload must include a valid filename")
    if len(name) > 255 or any(ord(character) < 32 for character in name):
        raise UnsupportedDocumentFormat("The upload filename is not valid")
    return name


def _extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


def _has_pdf_header(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def _decode_text(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidTextEncoding("Text files must use UTF-8 or UTF-8 with BOM") from exc

    has_disallowed_control = any(
        ord(character) < 32 and character not in _ALLOWED_TEXT_CONTROLS for character in text
    )
    if has_disallowed_control:
        raise UnsupportedDocumentFormat("The uploaded content does not look like text")
    return text


def _extract_text_document(
    data: bytes,
    *,
    source_name: str,
    extension: str,
    max_characters: int,
) -> ExtractedDocument:
    if _has_pdf_header(data):
        raise UnsupportedDocumentFormat("File content does not match its text extension")

    text = _decode_text(data)
    if len(text) > max_characters:
        raise ExtractedTextLimitExceeded(
            f"Extracted text exceeds the {max_characters} character limit"
        )
    if not text.strip():
        raise EmptyDocument("The text file is empty or contains only whitespace")

    source_type, profile = _TEXT_PROFILES[extension]
    return ExtractedDocument(
        source_name=source_name,
        source_type=source_type,
        extraction_profile=profile,
        checksum_sha256=sha256(data).hexdigest(),
        file_size_bytes=len(data),
        reference_text=text,
        metadata={
            "encoding": "utf-8-sig",
            "normalization_applied": False,
            "offset_scope": "document_reference_text",
        },
    )


def _extract_pdf_document(
    data: bytes,
    *,
    source_name: str,
    max_pages: int,
    max_characters: int,
) -> ExtractedDocument:
    if not _has_pdf_header(data):
        raise UnsupportedDocumentFormat("File content does not match the PDF extension")

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise EncryptedPdf("Password-protected or encrypted PDFs are not supported")
        page_count = len(reader.pages)
    except EncryptedPdf:
        raise
    except (PdfReadError, ValueError, TypeError, KeyError, OSError) as exc:
        raise InvalidPdf("The PDF is damaged or cannot be parsed") from exc

    if page_count > max_pages:
        raise PdfPageLimitExceeded(f"PDF exceeds the {max_pages} page limit")

    parts: list[str] = []
    pages: list[ExtractedPage] = []
    extracted_character_count = 0
    cursor = 0

    for page_index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except (PdfReadError, ValueError, TypeError, KeyError, OSError) as exc:
            raise InvalidPdf("Text could not be extracted from the PDF") from exc

        extracted_character_count += len(text)
        if extracted_character_count > max_characters:
            raise ExtractedTextLimitExceeded(
                f"Extracted text exceeds the {max_characters} character limit"
            )

        if page_index:
            parts.append(PDF_PAGE_SEPARATOR)
            cursor += len(PDF_PAGE_SEPARATOR)
        start_char = cursor
        parts.append(text)
        cursor += len(text)
        pages.append(
            ExtractedPage(
                page_number=page_index + 1,
                text=text,
                start_char=start_char,
                end_char=cursor,
            )
        )

    reference_text = "".join(parts)
    if not reference_text.strip():
        raise NoUsablePdfText(
            "PDF text extraction produced no usable text; the file may require OCR"
        )

    return ExtractedDocument(
        source_name=source_name,
        source_type="pdf",
        extraction_profile=_PDF_PROFILE,
        checksum_sha256=sha256(data).hexdigest(),
        file_size_bytes=len(data),
        reference_text=reference_text,
        pages=tuple(pages),
        metadata={
            "parser": "pypdf",
            "parser_version": pypdf_version,
            "page_count": page_count,
            "normalization_applied": False,
            "offset_scope": "document_reference_text",
            "page_separator": "LF-FF-LF",
        },
    )


def extract_document(
    data: bytes,
    *,
    filename: str | None,
    max_pdf_pages: int,
    max_characters: int,
) -> ExtractedDocument:
    """Validate content and extract an in-memory upload without executing it."""
    source_name = _safe_display_name(filename)
    extension = _extension(source_name)

    if not data:
        raise EmptyDocument("The uploaded file is empty")
    if extension in _TEXT_PROFILES:
        return _extract_text_document(
            data,
            source_name=source_name,
            extension=extension,
            max_characters=max_characters,
        )
    if extension == ".pdf":
        return _extract_pdf_document(
            data,
            source_name=source_name,
            max_pages=max_pdf_pages,
            max_characters=max_characters,
        )
    raise UnsupportedDocumentFormat("Only .txt, .md, and text-based .pdf files are supported")
