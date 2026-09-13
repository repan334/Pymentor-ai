from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from app.core.config import Settings
from app.embeddings.gemini import (
    GeminiEmbeddingAdapter,
    format_document_input,
    format_query_input,
)
from app.embeddings.models import (
    DocumentEmbeddingInput,
    EmbeddingAuthenticationError,
    EmbeddingQuotaError,
    EmbeddingTimeoutError,
    EmbeddingValidationError,
    validate_vectors,
)
from google.genai import errors


@dataclass
class FakeEmbedding:
    values: list[float] | None


@dataclass
class FakeResponse:
    embeddings: list[FakeEmbedding] | None


class FakeModels:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def embed_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.models = FakeModels(outcomes)


def _settings(**overrides: Any) -> Settings:
    values = {
        "database_url": None,
        "gemini_api_key": None,
        "embedding_retry_base_seconds": 0,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def _response(count: int, dimensions: int = 768) -> FakeResponse:
    return FakeResponse(
        embeddings=[FakeEmbedding([1.0, *([0.0] * (dimensions - 1))]) for _ in range(count)]
    )


def test_retrieval_formats_are_asymmetric_and_preserve_source_content() -> None:
    source = "def answer():\n    return 42"

    document = format_document_input(DocumentEmbeddingInput(content=source, title="Functions"))
    query = format_query_input("How does return work?")

    assert document == f"title: Functions | text: {source}"
    assert query == "task: search result | query: How does return work?"
    assert source in document


def test_each_document_is_sent_as_a_separate_content_and_yields_one_vector() -> None:
    client = FakeClient([_response(2)])
    adapter = GeminiEmbeddingAdapter(_settings(), client=client)

    vectors = adapter.embed_documents(
        [
            DocumentEmbeddingInput("chunk one", "lesson.md"),
            DocumentEmbeddingInput("chunk two", "lesson.md"),
        ]
    )

    call = client.models.calls[0]
    assert len(vectors) == 2
    assert len(call["contents"]) == 2
    assert call["contents"][0].parts[0].text == "title: lesson.md | text: chunk one"
    assert call["contents"][1].parts[0].text == "title: lesson.md | text: chunk two"
    assert call["config"].task_type is None
    assert call["config"].output_dimensionality == 768


@pytest.mark.parametrize(
    "vectors",
    [
        [[1.0] * 767],
        [[float("nan"), *([1.0] * 767)]],
        [[float("inf"), *([1.0] * 767)]],
        [[0.0] * 768],
        [],
    ],
)
def test_vector_validation_rejects_wrong_or_unsafe_provider_results(
    vectors: list[list[float]],
) -> None:
    with pytest.raises(EmbeddingValidationError):
        validate_vectors(vectors, expected_count=1, dimensions=768)


def test_missing_embedding_values_is_rejected() -> None:
    client = FakeClient([FakeResponse([FakeEmbedding(None)])])
    adapter = GeminiEmbeddingAdapter(_settings(), client=client)

    with pytest.raises(EmbeddingValidationError):
        adapter.embed_query("question")


def test_transient_quota_is_retried_with_one_owned_retry_layer() -> None:
    sleeps: list[float] = []
    quota = errors.APIError(
        429,
        {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}},
    )
    client = FakeClient([quota, _response(1)])
    adapter = GeminiEmbeddingAdapter(
        _settings(embedding_max_attempts=2, embedding_retry_base_seconds=0.25),
        client=client,
        sleep=sleeps.append,
    )

    vector = adapter.embed_query("question")

    assert len(vector) == 768
    assert len(client.models.calls) == 2
    assert sleeps == [0.25]


def test_quota_stops_after_configured_attempt_limit() -> None:
    quota = errors.APIError(
        429,
        {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}},
    )
    client = FakeClient([quota, quota])
    adapter = GeminiEmbeddingAdapter(
        _settings(embedding_max_attempts=2), client=client, sleep=lambda _: None
    )

    with pytest.raises(EmbeddingQuotaError):
        adapter.embed_query("question")
    assert len(client.models.calls) == 2


def test_authentication_failure_is_not_retried() -> None:
    auth = errors.APIError(
        401,
        {"error": {"code": 401, "message": "invalid key", "status": "UNAUTHENTICATED"}},
    )
    client = FakeClient([auth, _response(1)])
    adapter = GeminiEmbeddingAdapter(
        _settings(embedding_max_attempts=3), client=client, sleep=lambda _: None
    )

    with pytest.raises(EmbeddingAuthenticationError):
        adapter.embed_query("question")
    assert len(client.models.calls) == 1


def test_timeout_retries_only_to_the_configured_limit() -> None:
    client = FakeClient([TimeoutError(), TimeoutError()])
    adapter = GeminiEmbeddingAdapter(
        _settings(embedding_max_attempts=2), client=client, sleep=lambda _: None
    )

    with pytest.raises(EmbeddingTimeoutError):
        adapter.embed_query("question")
    assert len(client.models.calls) == 2
