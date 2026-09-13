import os

import pytest
from app.core.config import Settings
from app.embeddings.gemini import GeminiEmbeddingAdapter
from app.embeddings.models import DocumentEmbeddingInput

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_GEMINI_TESTS") != "1",
    reason="set RUN_GEMINI_TESTS=1 to call the configured Gemini model",
)


def test_live_gemini_returns_one_valid_768_vector_per_content() -> None:
    settings = Settings().model_copy(update={"embedding_max_attempts": 1})
    adapter = GeminiEmbeddingAdapter(settings)
    try:
        vectors = adapter.embed_documents(
            [
                DocumentEmbeddingInput("A Python function can return a value.", "lesson.txt"),
                DocumentEmbeddingInput("A for loop iterates over items.", "lesson.txt"),
            ]
        )
    finally:
        adapter.close()

    assert len(vectors) == 2
    assert all(len(vector) == 768 for vector in vectors)
    assert vectors[0] != vectors[1]
