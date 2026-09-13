from dataclasses import dataclass, field

MetadataValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A validated slice of text; offsets refer to the chunker's input."""

    content: str
    index: int
    start_char: int
    end_char: int
    metadata: dict[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")

        if not self.content.strip():
            raise ValueError("content must not be blank")

        for name in ("index", "start_char", "end_char"):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be an integer")

        if self.index < 0:
            raise ValueError("index must be non-negative")

        if self.start_char < 0:
            raise ValueError("start_char must be non-negative")

        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")

        if self.end_char - self.start_char != len(self.content):
            raise ValueError("character range must match content length")

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")

        object.__setattr__(self, "metadata", self.metadata.copy())

    @property
    def length(self) -> int:
        return len(self.content)
