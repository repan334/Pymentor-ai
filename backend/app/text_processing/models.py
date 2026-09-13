from dataclasses import dataclass, field

MetadataValue = str | int | float | bool | None


@dataclass(slots=True)
class TextChunk:
    """A validated piece of normalized document text."""

    content: str
    index: int
    start_char: int
    end_char: int
    metadata: dict[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        raise NotImplementedError

    @property
    def length(self) -> int:
        raise NotImplementedError
