from dataclasses import dataclass

from app.text_processing.models import MetadataValue, TextChunk


@dataclass(frozen=True, slots=True)
class TextChunker:
    """Split text into fixed-size character windows with overlap."""

    chunk_size: int = 500
    overlap: int = 100

    def __post_init__(self) -> None:
        for name in ("chunk_size", "overlap"):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be an integer")

        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")

        if self.overlap < 0 or self.overlap >= self.chunk_size:
            raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")

    def split(
        self,
        text: str,
        metadata: dict[str, MetadataValue] | None = None,
    ) -> list[TextChunk]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary or None")

        chunks: list[TextChunk] = []
        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(start + self.chunk_size, text_length)
            content = text[start:end]

            if content.strip():
                chunks.append(
                    TextChunk(
                        content=content,
                        index=len(chunks),
                        start_char=start,
                        end_char=end,
                        metadata={} if metadata is None else metadata,
                    )
                )

            if end == text_length:
                break

            start = end - self.overlap

        return chunks
