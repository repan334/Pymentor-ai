from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    provider: str
    model: str
    dimensions: int
    input_version: str

    @property
    def key(self) -> str:
        return ":".join((self.provider, self.model, str(self.dimensions), self.input_version))


@dataclass(frozen=True, slots=True)
class DocumentEmbeddingInput:
    content: str
    title: str | None = None


class EmbeddingError(RuntimeError):
    code = "embedding_failed"


class EmbeddingConfigurationError(EmbeddingError):
    code = "embedding_not_configured"


class EmbeddingAuthenticationError(EmbeddingError):
    code = "embedding_authentication_failed"


class EmbeddingInvalidRequestError(EmbeddingError):
    code = "embedding_request_invalid"


class EmbeddingQuotaError(EmbeddingError):
    code = "embedding_quota_exceeded"


class EmbeddingTimeoutError(EmbeddingError):
    code = "embedding_timeout"


class EmbeddingUnavailableError(EmbeddingError):
    code = "embedding_provider_unavailable"


class EmbeddingValidationError(EmbeddingError):
    code = "embedding_response_invalid"


class EmbeddingAdapter(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    def embed_documents(self, inputs: Sequence[DocumentEmbeddingInput]) -> list[list[float]]: ...

    def embed_query(self, query: str) -> list[float]: ...


def validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    dimensions: int,
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise EmbeddingValidationError(
            f"Provider returned {len(vectors)} vectors for {expected_count} inputs"
        )

    validated: list[list[float]] = []
    for vector in vectors:
        values = [float(value) for value in vector]
        if len(values) != dimensions:
            raise EmbeddingValidationError(
                f"Provider returned dimension {len(values)}; expected {dimensions}"
            )
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingValidationError("Provider returned a non-finite vector value")
        if math.sqrt(sum(value * value for value in values)) == 0:
            raise EmbeddingValidationError("Provider returned a zero-norm vector")
        validated.append(values)
    return validated
