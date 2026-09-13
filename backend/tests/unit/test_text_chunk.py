import pytest

from app.text_processing.models import TextChunk
from dataclasses import FrozenInstanceError


def test_text_chunk_stores_valid_data() -> None:
    chunk = TextChunk(
        content="Python basics",
        index=0,
        start_char=0,
        end_char=13,
        metadata={"page": 1},
    )

    assert chunk.content == "Python basics"
    assert chunk.index == 0
    assert chunk.start_char == 0
    assert chunk.end_char == 13
    assert chunk.metadata == {"page": 1}
    assert chunk.length == 13


def test_text_chunk_metadata_is_not_shared() -> None:
    first = TextChunk(content="A", index=0, start_char=0, end_char=1)
    second = TextChunk(content="B", index=1, start_char=1, end_char=2)

    first.metadata["page"] = 1

    assert second.metadata == {}


def test_text_chunk_rejects_non_string_content() -> None:
    with pytest.raises(TypeError, match="content must be a string"):
        TextChunk(content=None, index=0, start_char=0, end_char=1)


@pytest.mark.parametrize("content", ["", " ", "\n", "\t"])
def test_text_chunk_rejects_blank_content(content: str) -> None:
    with pytest.raises(ValueError, match="content must not be blank"):
        TextChunk(content=content, index=0, start_char=0, end_char=len(content))


@pytest.mark.parametrize("index", [True, 1.5, "0"])
def test_text_chunk_rejects_non_integer_index(index: object) -> None:
    with pytest.raises(TypeError, match="index must be an integer"):
        TextChunk(content="A", index=index, start_char=0, end_char=1)


def test_text_chunk_rejects_negative_index() -> None:
    with pytest.raises(ValueError, match="index must be non-negative"):
        TextChunk(content="A", index=-1, start_char=0, end_char=1)


def test_text_chunk_rejects_negative_start_character() -> None:
    with pytest.raises(ValueError, match="start_char must be non-negative"):
        TextChunk(content="A", index=0, start_char=-1, end_char=0)


@pytest.mark.parametrize(
    ("start_char", "end_char"),
    [
        (5, 5),
        (5, 4),
    ],
)
def test_text_chunk_requires_end_after_start(
    start_char: int,
    end_char: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="end_char must be greater than start_char",
    ):
        TextChunk(
            content="A",
            index=0,
            start_char=start_char,
            end_char=end_char,
        )


def test_text_chunk_requires_range_to_match_content_length() -> None:
    with pytest.raises(
        ValueError,
        match="character range must match content length",
    ):
        TextChunk(
            content="Python",
            index=0,
            start_char=10,
            end_char=15,
        )


def test_text_chunk_rejects_non_dictionary_metadata() -> None:
    with pytest.raises(TypeError, match="metadata must be a dictionary"):
        TextChunk(
            content="A",
            index=0,
            start_char=0,
            end_char=1,
            metadata=[],
        )


@pytest.mark.parametrize("field_name", ["start_char", "end_char"])
@pytest.mark.parametrize("bad_value", [True, 1.5, "0", None])
def test_text_chunk_rejects_non_integer_offsets(
    field_name: str,
    bad_value: object,
) -> None:
    values = {
        "content": "A",
        "index": 0,
        "start_char": 0,
        "end_char": 1,
    }
    values[field_name] = bad_value

    with pytest.raises(TypeError, match=f"{field_name} must be an integer"):
        TextChunk(**values)


def test_text_chunk_copies_supplied_metadata() -> None:
    metadata = {"page": 1}
    chunk = TextChunk(
        content="A",
        index=0,
        start_char=0,
        end_char=1,
        metadata=metadata,
    )

    metadata["page"] = 99

    assert chunk.metadata == {"page": 1}


def test_text_chunk_rejects_content_reassignment() -> None:
    chunk = TextChunk(content="A", index=0, start_char=0, end_char=1)

    with pytest.raises(FrozenInstanceError):
        chunk.content = "Changed"
