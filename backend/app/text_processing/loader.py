from pathlib import Path


def load_text_file(path: str | Path) -> str:
    """Read a UTF-8 TXT file without translating its line endings."""
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be a string or Path")

    file_path = Path(path)

    if file_path.suffix.lower() != ".txt":
        raise ValueError("only .txt files are supported")

    with file_path.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return file.read()
