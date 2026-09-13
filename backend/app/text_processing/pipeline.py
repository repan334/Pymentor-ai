from dataclasses import dataclass
from pathlib import Path

from app.text_processing.chunker import TextChunker
from app.text_processing.loader import load_text_file
from app.text_processing.models import TextChunk
from app.text_processing.normalizer import normalize_text


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """Raw source, selected reference text, and chunks addressed within that text."""

    source_name: str
    source_text: str
    processed_text: str
    normalization_applied: bool
    chunks: tuple[TextChunk, ...]


def process_text_file(
    path: str | Path,
    *,
    chunker: TextChunker,
    normalize: bool = False,
) -> ProcessedDocument:
    """Read a TXT file and chunk raw text unless normalization is explicitly enabled.

    Chunk offsets always address ``processed_text``. With the conservative default,
    ``processed_text`` is exactly ``source_text``; after normalization it is a
    distinct coordinate space.
    """
    if not isinstance(chunker, TextChunker):
        raise TypeError("chunker must be a TextChunker")

    if type(normalize) is not bool:
        raise TypeError("normalize must be a boolean")

    source_text = load_text_file(path)
    source_name = Path(path).name

    processed_text = normalize_text(source_text) if normalize else source_text

    chunks = chunker.split(
        processed_text,
        metadata={
            "source": source_name,
            "normalized": normalize,
        },
    )

    return ProcessedDocument(
        source_name=source_name,
        source_text=source_text,
        processed_text=processed_text,
        normalization_applied=normalize,
        chunks=tuple(chunks),
    )
