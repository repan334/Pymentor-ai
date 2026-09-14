from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any, TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.chat.models import (
    ChatAuthenticationError,
    ChatConfigurationError,
    ChatInvalidRequestError,
    ChatOutputInvalidError,
    ChatQuotaError,
    ChatSafetyBlockedError,
    ChatTimeoutError,
    ChatTruncatedError,
    ChatUnavailableError,
    GenerationUsage,
    ModelTutorOutput,
    TutorSource,
)
from app.chat.prompt import TUTOR_SYSTEM_INSTRUCTION, build_user_prompt
from app.core.config import Settings

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class GeminiChatAdapter:
    """One-shot structured generation with bounded application-owned retries."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client = client
        self._sleep = sleep
        self.last_usage: GenerationUsage | None = None

    @property
    def profile(self) -> str:
        return self._settings.llm_profile_key

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                key = self._settings.gemini_key_value
            except ValueError as exc:
                raise ChatConfigurationError(str(exc)) from exc
            self._client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    api_version=self._settings.gemini_api_version,
                    timeout=self._settings.chat_request_timeout_seconds * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._client

    def close(self) -> None:
        close = getattr(self._client, "close", None) if self._client is not None else None
        if close is not None:
            close()

    def generate(
        self,
        *,
        question: str,
        sources: Sequence[TutorSource],
    ) -> ModelTutorOutput:
        return self.generate_structured(
            prompt=build_user_prompt(question, sources),
            system_instruction=TUTOR_SYSTEM_INSTRUCTION,
            response_model=ModelTutorOutput,
        )

    def generate_structured(
        self,
        *,
        prompt: str,
        system_instruction: str,
        response_model: type[StructuredModel],
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> StructuredModel:
        response, attempts = self._call_with_retry(
            prompt,
            system_instruction=system_instruction,
            response_model=response_model,
            max_output_tokens=max_output_tokens or self._settings.chat_max_output_tokens,
            thinking_budget=(
                self._settings.chat_thinking_budget if thinking_budget is None else thinking_budget
            ),
            temperature=self._settings.chat_temperature if temperature is None else temperature,
        )
        self.last_usage = _usage_from_response(response, attempts)
        return _parse_response(response, response_model)

    def _call_with_retry(
        self,
        prompt: str,
        *,
        system_instruction: str,
        response_model: type[BaseModel],
        max_output_tokens: int,
        thinking_budget: int,
        temperature: float,
    ) -> tuple[Any, int]:
        last_error: Exception | None = None
        for attempt in range(1, self._settings.chat_max_attempts + 1):
            try:
                response = self._get_client().models.generate_content(
                    model=self._settings.llm_model,
                    contents=types.Content(role="user", parts=[types.Part(text=prompt)]),
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=thinking_budget,
                            include_thoughts=False,
                        ),
                        response_mime_type="application/json",
                        response_schema=_provider_response_schema(response_model),
                        candidate_count=1,
                    ),
                )
                return response, attempt
            except Exception as exc:
                translated, retryable = _translate_provider_error(exc)
                last_error = translated
                if not retryable or attempt == self._settings.chat_max_attempts:
                    raise translated from exc
                delay = self._settings.chat_retry_base_seconds * (2 ** (attempt - 1))
                self._sleep(delay)
        raise ChatUnavailableError("Chat provider call failed") from last_error


def _parse_response(response: Any, response_model: type[StructuredModel]) -> StructuredModel:
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback is not None else None
    if block_reason not in {None, types.BlockedReason.BLOCKED_REASON_UNSPECIFIED}:
        raise ChatSafetyBlockedError("Gemini blocked the input for safety")

    candidates = getattr(response, "candidates", None) or []
    if len(candidates) != 1:
        raise ChatOutputInvalidError("Gemini returned an unexpected candidate count")
    finish_reason = getattr(candidates[0], "finish_reason", None)
    if finish_reason == types.FinishReason.MAX_TOKENS:
        raise ChatTruncatedError("Gemini output reached the configured token limit")
    safety_reasons = {
        types.FinishReason.SAFETY,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.SPII,
        types.FinishReason.IMAGE_SAFETY,
    }
    if finish_reason in safety_reasons:
        raise ChatSafetyBlockedError("Gemini blocked the output for safety")
    if finish_reason != types.FinishReason.STOP:
        raise ChatOutputInvalidError("Gemini did not finish with a complete response")

    try:
        parts = getattr(getattr(candidates[0], "content", None), "parts", None)
        if parts:
            return response_model.model_validate_json(_candidate_text(candidates[0]))
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, response_model):
            return parsed
        return response_model.model_validate(parsed)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ChatOutputInvalidError("Gemini returned malformed structured output") from exc


def _candidate_text(candidate: Any) -> str:
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if not parts:
        raise ChatOutputInvalidError("Gemini response contains no text")
    text = "".join(part.text or "" for part in parts)
    if not text:
        raise ChatOutputInvalidError("Gemini response contains no text")
    return text


def _provider_response_schema(
    response_model: type[BaseModel] = ModelTutorOutput,
) -> dict[str, Any]:
    schema = deepcopy(response_model.model_json_schema())

    def remove_unsupported(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("additionalProperties", None)
            for child in value.values():
                remove_unsupported(child)
        elif isinstance(value, list):
            for child in value:
                remove_unsupported(child)

    remove_unsupported(schema)
    return schema


def _usage_from_response(response: Any, attempts: int) -> GenerationUsage:
    usage = getattr(response, "usage_metadata", None)
    return GenerationUsage(
        model_version=getattr(response, "model_version", None),
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        thinking_tokens=getattr(usage, "thoughts_token_count", None),
        attempts=attempts,
    )


def _translate_provider_error(exc: Exception) -> tuple[Exception, bool]:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return ChatTimeoutError("Gemini chat request timed out"), True
    if isinstance(exc, errors.APIError):
        code = exc.code
        if code in {401, 403}:
            return ChatAuthenticationError("Gemini authentication failed"), False
        if code == 400:
            return ChatInvalidRequestError("Gemini rejected the chat request"), False
        if code == 429:
            return ChatQuotaError("Gemini chat quota is exhausted"), True
        if code in {408, 500, 502, 503, 504}:
            return ChatUnavailableError("Gemini chat is temporarily unavailable"), True
        return ChatUnavailableError("Gemini chat request failed"), False
    if isinstance(exc, httpx.TransportError):
        return ChatUnavailableError("Gemini chat transport failed"), True
    return ChatUnavailableError("Gemini chat request failed"), False
