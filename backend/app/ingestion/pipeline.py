from app.ingestion.models import PreparedChunk, PreparedDocument
from app.ingestion.readers import extract_document
from app.text_processing.chunker import TextChunker


def prepare_document(
    data: bytes,
    *,
    filename: str | None,
    max_pdf_pages: int,
    max_characters: int,
    chunk_size: int,
    chunk_overlap: int,
) -> PreparedDocument:
    """Extract and chunk an upload while keeping document-global character offsets."""
    extracted = extract_document(
        data,
        filename=filename,
        max_pdf_pages=max_pdf_pages,
        max_characters=max_characters,
    )
    chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap)
    chunks: list[PreparedChunk] = []

    segments = extracted.pages or (None,)
    for page in segments:
        segment_text = extracted.reference_text if page is None else page.text
        segment_start = 0 if page is None else page.start_char
        page_number = None if page is None else page.page_number

        for chunk in chunker.split(segment_text):
            start_char = segment_start + chunk.start_char
            end_char = segment_start + chunk.end_char
            metadata = {
                "source_name": extracted.source_name,
                "source_type": extracted.source_type,
                "normalization_applied": False,
                "offset_scope": "document_reference_text",
            }
            if page_number is not None:
                metadata["page_number"] = page_number

            prepared = PreparedChunk(
                index=len(chunks),
                content=chunk.content,
                start_char=start_char,
                end_char=end_char,
                page_number=page_number,
                metadata=metadata,
            )
            if (
                extracted.reference_text[prepared.start_char : prepared.end_char]
                != prepared.content
            ):
                raise RuntimeError("chunk offsets do not address the reference text")
            chunks.append(prepared)

    return PreparedDocument(extracted=extracted, chunks=tuple(chunks))
