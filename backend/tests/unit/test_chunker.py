import pytest

from app.text_processing.chunker import TextChunker


def test_chunker_produces_expected_overlap() -> None:
    chunks = TextChunker(chunk_size=5, overlap=2).split("ABCDEFGHIJK")

    assert [chunk.content for chunk in chunks] == ["ABCDE", "DEFGH", "GHIJK"]
    assert [chunk.index for chunk in chunks] == [0, 1, 2]
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [
        (0, 5),
        (3, 8),
        (6, 11),
    ]


def test_chunker_handles_short_input() -> None:
    chunks = TextChunker(chunk_size=5, overlap=2).split("ABC")

    assert len(chunks) == 1
    assert chunks[0].content == "ABC"
    assert chunks[0].end_char == 3


def test_chunker_does_not_duplicate_exact_size_input() -> None:
    chunks = TextChunker(chunk_size=5, overlap=2).split("ABCDE")

    assert len(chunks) == 1
    assert chunks[0].content == "ABCDE"


def test_chunker_without_overlap_preserves_tail() -> None:
    chunks = TextChunker(chunk_size=4, overlap=0).split("ABCDEFGHI")

    assert [chunk.content for chunk in chunks] == ["ABCD", "EFGH", "I"]
    assert "".join(chunk.content for chunk in chunks) == "ABCDEFGHI"


@pytest.mark.parametrize("text", ["", " ", "\n\t  \n"])
def test_chunker_returns_no_chunks_for_blank_input(text: str) -> None:
    assert TextChunker(chunk_size=2, overlap=1).split(text) == []


def test_chunker_skips_blank_windows_without_breaking_indexes() -> None:
    chunks = TextChunker(chunk_size=3, overlap=0).split("   ABC   DEF")

    assert [chunk.content for chunk in chunks] == ["ABC", "DEF"]
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert [chunk.start_char for chunk in chunks] == [3, 9]


def test_chunker_preserves_exact_source_slices() -> None:
    text = 'def greet():\n    return "Halo 😀"\n'
    chunks = TextChunker(chunk_size=12, overlap=3).split(text)

    for chunk in chunks:
        assert chunk.content == text[chunk.start_char : chunk.end_char]
        assert chunk.length == chunk.end_char - chunk.start_char
        assert 0 < chunk.length <= 12

    covered = {position for chunk in chunks for position in range(chunk.start_char, chunk.end_char)}
    assert all(
        position in covered for position, character in enumerate(text) if not character.isspace()
    )


def test_chunker_keeps_metadata_independent() -> None:
    metadata = {"page": 3}
    chunks = TextChunker(chunk_size=5, overlap=2).split("ABCDEFGHIJK", metadata)

    metadata["page"] = 99
    chunks[0].metadata["page"] = 7

    assert chunks[1].metadata == {"page": 3}


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "error"),
    [
        (True, 0, TypeError),
        (2.5, 0, TypeError),
        (5, True, TypeError),
        (5, "2", TypeError),
        (0, 0, ValueError),
        (-1, 0, ValueError),
        (5, -1, ValueError),
        (5, 5, ValueError),
        (5, 6, ValueError),
    ],
)
def test_chunker_rejects_invalid_configuration(
    chunk_size: object,
    overlap: object,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        TextChunker(chunk_size=chunk_size, overlap=overlap)


def test_chunker_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="text must be a string"):
        TextChunker().split(None)


def test_chunker_rejects_invalid_metadata_even_for_empty_text() -> None:
    with pytest.raises(TypeError, match="metadata must be a dictionary or None"):
        TextChunker().split("", metadata=[])


def test_chunker_handles_maximum_allowed_overlap() -> None:
    chunks = TextChunker(chunk_size=3, overlap=2).split("ABCDE")

    assert [chunk.content for chunk in chunks] == ["ABC", "BCD", "CDE"]
