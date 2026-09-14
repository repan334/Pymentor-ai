from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

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
    ModelTutorOutput,
    TutorSource,
)
from app.chat.prompt import TUTOR_SYSTEM_INSTRUCTION, build_user_prompt
from app.core.config import Settings


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
        prompt = build_user_prompt(question, sources)
        response = self._call_with_retry(prompt)
        return _parse_response(response)

    def _call_with_retry(self, prompt: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._settings.chat_max_attempts + 1):
            try:
                return self._get_client().models.generate_content(
                    model=self._settings.llm_model,
                    contents=types.Content(role="user", parts=[types.Part(text=prompt)]),
                    config=types.GenerateContentConfig(
                        system_instruction=TUTOR_SYSTEM_INSTRUCTION,
                        temperature=self._settings.chat_temperature,
                        max_output_tokens=self._settings.chat_max_output_tokens,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=self._settings.chat_thinking_budget,
                            include_thoughts=False,
                        ),
                        response_mime_type="application/json",
                        response_schema=_provider_response_schema(),
                        candidate_count=1,
                    ),
                )
            except Exception as exc:
                translated, retryable = _translate_provider_error(exc)
                last_error = translated
                if not retryable or attempt == self._settings.chat_max_attempts:
                    raise translated from exc
                delay = self._settings.chat_retry_base_seconds * (2 ** (attempt - 1))
                self._sleep(delay)
        raise ChatUnavailableError("Chat provider call failed") from last_error


def _parse_response(response: Any) -> ModelTutorOutput:
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
            return ModelTutorOutput.model_validate_json(_candidate_text(candidates[0]))
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, ModelTutorOutput):
            return parsed
        return ModelTutorOutput.model_validate(parsed)
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


def _provider_response_schema() -> dict[str, Any]:
    schema = deepcopy(ModelTutorOutput.model_json_schema())

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
