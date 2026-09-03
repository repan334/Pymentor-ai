import re

_MULTIPLE_NEWLINES_PATTERN = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Normalize extracted document text while preserving paragraphs."""
    # 1-2. Validate input type.
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    # 3. Normalize Windows newlines.
    text = text.replace("\r\n", "\n")

    # 4. Normalize old Mac newlines.
    text = text.replace("\r", "\n")

    # 5. Split into lines.
    lines = text.split("\n")

    # 6. Remove trailing whitespace while preserving leading indentation.
    cleaned_lines = [line.rstrip() for line in lines]

    # 7. Rejoin lines.
    text = "\n".join(cleaned_lines)

    # 8. Collapse 3+ consecutive newlines down to exactly 2.
    text = _MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text)

    # 9. Remove only leading and trailing newlines from the whole text.
    text = text.strip("\n")

    # 10. Return result.
    return text
