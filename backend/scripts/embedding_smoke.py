"""Validate one live Gemini embedding without printing secrets or vector values."""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.embeddings.gemini import GeminiEmbeddingAdapter  # noqa: E402
from app.embeddings.models import EmbeddingError  # noqa: E402


def main() -> int:
    settings = get_settings()
    adapter = GeminiEmbeddingAdapter(settings)
    actual_dimensions: int | None = None
    valid = False
    error_code: str | None = None
    try:
        vector = adapter.embed_query("Bagaimana fungsi Python mengembalikan hasil?")
        actual_dimensions = len(vector)
        valid = actual_dimensions == settings.embedding_dimensions
    except EmbeddingError as exc:
        error_code = exc.code
    finally:
        adapter.close()

    print(f"provider={settings.embedding_provider}")
    print(f"model={settings.embedding_model}")
    print(f"expected_dimensions={settings.embedding_dimensions}")
    actual = actual_dimensions if actual_dimensions is not None else "unavailable"
    print(f"actual_dimensions={actual}")
    print(f"validation={'passed' if valid else 'failed'}")
    if error_code is not None:
        print(f"error={error_code}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
