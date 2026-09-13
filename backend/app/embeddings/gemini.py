from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.core.config import Settings
from app.embeddings.models import (
    DocumentEmbeddingInput,
    EmbeddingAuthenticationError,
    EmbeddingConfigurationError,
    EmbeddingInvalidRequestError,
    EmbeddingProfile,
    EmbeddingQuotaError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
    EmbeddingValidationError,
    validate_vectors,
)

DOCUMENT_TEMPLATE = "title: {title} | text: {content}"
QUERY_TEMPLATE = "task: search result | query: {query}"


def format_document_input(value: DocumentEmbeddingInput) -> str:
    title = value.title.strip() if value.title and value.title.strip() else "none"
    return DOCUMENT_TEMPLATE.format(title=title, content=value.content)


def format_query_input(query: str) -> str:
    return QUERY_TEMPLATE.format(query=query)


class GeminiEmbeddingAdapter:
    """Synchronous Gemini adapter with one bounded retry layer owned by this class."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._profile = EmbeddingProfile(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            input_version=settings.embedding_input_version,
        )
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                key = self._settings.gemini_key_value
            except ValueError as exc:
                raise EmbeddingConfigurationError(str(exc)) from exc
            self._client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    timeout=self._settings.embedding_request_timeout_seconds * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._client

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    def close(self) -> None:
        close = getattr(self._client, "close", None) if self._client is not None else None
        if close is not None:
            close()

    def embed_documents(self, inputs: Sequence[DocumentEmbeddingInput]) -> list[list[float]]:
        if not inputs:
            return []
        formatted = [format_document_input(item) for item in inputs]
        return self._embed(formatted)

    def embed_query(self, query: str) -> list[float]:
        return self._embed([format_query_input(query)])[0]

    def _embed(self, inputs: Sequence[str]) -> list[list[float]]:
        # Separate Content objects are essential: a flat list of strings can be
        # interpreted as parts of one content and yield only one vector.
        contents = [types.Content(role="user", parts=[types.Part(text=value)]) for value in inputs]
        response = self._call_with_retry(contents)
        embeddings = getattr(response, "embeddings", None)
        if embeddings is None:
            raise EmbeddingValidationError("Provider response contains no embeddings")
        vectors = []
        for embedding in embeddings:
            values = getattr(embedding, "values", None)
            if values is None:
                raise EmbeddingValidationError("Provider embedding contains no values")
            vectors.append(values)
        return validate_vectors(
            vectors,
            expected_count=len(inputs),
            dimensions=self.profile.dimensions,
        )

    def _call_with_retry(self, contents: list[types.Content]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._settings.embedding_max_attempts + 1):
            try:
                return self._get_client().models.embed_content(
                    model=self.profile.model,
                    contents=contents,
                    config=types.EmbedContentConfig(
                        output_dimensionality=self.profile.dimensions,
                    ),
                )
            except Exception as exc:
                translated, retryable = _translate_provider_error(exc)
                last_error = translated
                if not retryable or attempt == self._settings.embedding_max_attempts:
                    raise translated from exc
                delay = self._settings.embedding_retry_base_seconds * (2 ** (attempt - 1))
                self._sleep(delay)
        raise EmbeddingUnavailableError("Embedding provider call failed") from last_error


def _translate_provider_error(exc: Exception) -> tuple[Exception, bool]:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return EmbeddingTimeoutError("Embedding provider request timed out"), True
    if isinstance(exc, errors.APIError):
        code = exc.code
        if code in {401, 403}:
            return EmbeddingAuthenticationError("Gemini authentication failed"), False
        if code == 400:
            return EmbeddingInvalidRequestError("Gemini rejected the embedding request"), False
        if code == 429:
            return EmbeddingQuotaError("Gemini embedding quota is exhausted"), True
        if code in {408, 500, 502, 503, 504}:
            return EmbeddingUnavailableError("Gemini embedding is temporarily unavailable"), True
        return EmbeddingUnavailableError("Gemini embedding request failed"), False
    if isinstance(exc, httpx.TransportError):
        return EmbeddingUnavailableError("Embedding provider transport failed"), True
    return EmbeddingUnavailableError("Embedding provider request failed"), False
