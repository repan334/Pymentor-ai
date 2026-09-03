import pytest
from app.text_processing.normalizer import normalize_text


def test_normalize_text_preserves_python_indentation() -> None:
    raw_text = 'def greet(name):\r\n    message = f"Hello,  {name}"\r\n    return message  '

    result = normalize_text(raw_text)

    expected = 'def greet(name):\n    message = f"Hello,  {name}"\n    return message'
    assert result == expected


def test_normalize_text_standardizes_line_endings() -> None:
    raw_text = "Line one\r\nLine two\rLine three"

    result = normalize_text(raw_text)

    assert result == "Line one\nLine two\nLine three"


def test_normalize_text_preserves_paragraph_boundaries() -> None:
    raw_text = "Paragraph one.\n\n\n\nParagraph two."

    result = normalize_text(raw_text)

    assert result == "Paragraph one.\n\nParagraph two."


def test_normalize_text_removes_trailing_whitespace_from_lines() -> None:
    raw_text = "First line  \n    indented line\t "

    result = normalize_text(raw_text)

    assert result == "First line\n    indented line"


def test_normalize_text_returns_empty_string_for_whitespace_only_input() -> None:
    assert normalize_text(" \t\n\t ") == ""


def test_normalize_text_returns_empty_string_for_empty_input() -> None:
    assert normalize_text("") == ""


def test_normalize_text_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="text must be a string"):
        normalize_text(None)
