class IngestionError(ValueError):
    """Base class for expected document ingestion failures."""

    code = "document_unprocessable"


class UnsupportedDocumentFormat(IngestionError):
    code = "unsupported_format"


class FileSizeLimitExceeded(IngestionError):
    code = "file_too_large"


class EmptyDocument(IngestionError):
    code = "empty_document"


class InvalidTextEncoding(IngestionError):
    code = "invalid_encoding"


class InvalidPdf(IngestionError):
    code = "invalid_pdf"


class EncryptedPdf(IngestionError):
    code = "encrypted_pdf"


class PdfPageLimitExceeded(IngestionError):
    code = "pdf_page_limit_exceeded"


class ExtractedTextLimitExceeded(IngestionError):
    code = "extracted_text_limit_exceeded"


class NoUsablePdfText(IngestionError):
    code = "no_usable_pdf_text"
