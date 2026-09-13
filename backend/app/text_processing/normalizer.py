import re

_MULTIPLE_NEWLINES_PATTERN = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Normalize prose whitespace while preserving indentation and internal spacing.

    Line-ending conversion, trailing-whitespace removal, and blank-line collapse can
    still change the contents of Python multiline string literals. Callers handling
    code should therefore keep normalization disabled unless that trade-off is wanted.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    lines = text.split("\n")
    cleaned_lines = [line.rstrip() for line in lines]
    text = "\n".join(cleaned_lines)

    text = _MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text)
    text = text.strip("\n")
    return text
