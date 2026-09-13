from pathlib import Path

import pytest

from app.text_processing.chunker import TextChunker
from app.text_processing.loader import load_text_file
from app.text_processing.pipeline import process_text_file


def test_loader_preserves_line_endings_and_unicode(tmp_path: Path) -> None:
    path = tmp_path / "lesson.txt"
    text = "Baris satu\r\nBelajar Python \rBaris tiga"
    path.write_bytes(text.encode("utf-8"))

    assert load_text_file(path) == text


def test_loader_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "lesson.TXT"
    path.write_bytes("Python".encode("utf-8-sig"))

    assert load_text_file(str(path)) == "Python"


def test_loader_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_text_file(tmp_path / "missing.txt")


def test_loader_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "lesson.pdf"
    path.write_bytes(b"Example")

    with pytest.raises(ValueError, match="only .txt files are supported"):
        load_text_file(path)


def test_loader_reports_invalid_encoding(tmp_path: Path) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(UnicodeDecodeError):
        load_text_file(path)


def test_loader_rejects_invalid_path_type() -> None:
    with pytest.raises(TypeError, match="path must be a string or Path"):
        load_text_file(None)


def test_pipeline_preserves_code_by_default(tmp_path: Path) -> None:
    path = tmp_path / "code.txt"
    text = 'message = """Hello  \r\n\r\n\r\nWorld"""\r\n'
    path.write_bytes(text.encode("utf-8"))

    result = process_text_file(
        path,
        chunker=TextChunker(chunk_size=200, overlap=0),
    )

    assert result.source_text == text
    assert result.processed_text == text
    assert result.normalization_applied is False
    assert len(result.chunks) == 1
    assert result.chunks[0].content == text


def test_pipeline_normalizes_prose_and_preserves_source(tmp_path: Path) -> None:
    path = tmp_path / "lesson.txt"
    text = "Python  \r\n\r\n\r\nFunctions\t "
    path.write_bytes(text.encode("utf-8"))

    result = process_text_file(
        path,
        chunker=TextChunker(chunk_size=8, overlap=2),
        normalize=True,
    )

    assert result.source_name == "lesson.txt"
    assert result.source_text == text
    assert result.processed_text == "Python\n\nFunctions"
    assert result.normalization_applied is True
    assert len(result.chunks) > 1

    for chunk in result.chunks:
        assert chunk.content == result.processed_text[chunk.start_char : chunk.end_char]
        assert chunk.metadata == {
            "source": "lesson.txt",
            "normalized": True,
        }


@pytest.mark.parametrize("normalize", [False, True])
def test_pipeline_handles_empty_file(tmp_path: Path, normalize: bool) -> None:
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")

    result = process_text_file(
        path,
        chunker=TextChunker(),
        normalize=normalize,
    )

    assert result.source_text == ""
    assert result.processed_text == ""
    assert result.chunks == ()


def test_pipeline_rejects_invalid_chunker(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="chunker must be a TextChunker"):
        process_text_file(tmp_path / "lesson.txt", chunker=None)


def test_pipeline_rejects_invalid_normalization_flag(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="normalize must be a boolean"):
        process_text_file(
            tmp_path / "lesson.txt",
            chunker=TextChunker(),
            normalize="false",
        )
