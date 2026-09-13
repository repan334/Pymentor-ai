from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    source_name: str
    source_type: str
    extraction_profile: str
    checksum_sha256: str
    file_size_bytes: int
    reference_text: str
    pages: tuple[ExtractedPage, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreparedChunk:
    index: int
    content: str
    start_char: int
    end_char: int
    page_number: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    extracted: ExtractedDocument
    chunks: tuple[PreparedChunk, ...]
