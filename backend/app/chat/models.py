from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ModelAnswerSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    reference_ids: list[str] = Field(default_factory=list, max_length=8)


class ModelTutorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "insufficient_context"]
    sections: list[ModelAnswerSection] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True, slots=True)
class TutorSource:
    reference_id: str
    document_id: int
    chunk_id: int
    source_name: str
    start_char: int
    end_char: int
    excerpt: str
    page_number: int | None


@dataclass(frozen=True, slots=True)
class GenerationUsage:
    model_version: str | None
    prompt_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    attempts: int


class ChatError(RuntimeError):
    code = "chat_generation_failed"


class ChatConfigurationError(ChatError):
    code = "chat_not_configured"


class ChatAuthenticationError(ChatError):
    code = "chat_authentication_failed"


class ChatInvalidRequestError(ChatError):
    code = "chat_request_invalid"


class ChatQuotaError(ChatError):
    code = "chat_quota_exceeded"


class ChatTimeoutError(ChatError):
    code = "chat_timeout"


class ChatUnavailableError(ChatError):
    code = "chat_provider_unavailable"


class ChatSafetyBlockedError(ChatError):
    code = "chat_safety_blocked"


class ChatTruncatedError(ChatError):
    code = "chat_output_truncated"


class ChatOutputInvalidError(ChatError):
    code = "chat_output_invalid"


class ChatAdapter(Protocol):
    @property
    def profile(self) -> str: ...

    def generate(
        self,
        *,
        question: str,
        sources: Sequence[TutorSource],
    ) -> ModelTutorOutput: ...
