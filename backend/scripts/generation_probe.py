"""Run one sanitized Gemini generation capability probe per invocation."""

import argparse
import re
import sys
from pathlib import Path
from typing import Literal

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.chat.gemini import GeminiChatAdapter  # noqa: E402
from app.chat.models import ChatError  # noqa: E402
from app.core.config import Settings  # noqa: E402
from google import genai  # noqa: E402
from google.genai import errors, types  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("minimal", "structured"))
    args = parser.parse_args()
    settings = Settings().model_copy(update={"chat_max_attempts": 1})
    print(f"provider={settings.llm_provider}")
    print(f"model={settings.llm_model}")
    print(f"api_version={settings.gemini_api_version}")
    print(f"stage={args.stage}")
    try:
        if args.stage == "minimal":
            valid, model_version = _minimal(settings)
        else:
            valid, model_version = _structured(settings)
        print(f"model_version={model_version or 'unavailable'}")
        print(f"validation={'passed' if valid else 'failed'}")
        return 0 if valid else 1
    except (ChatError, errors.APIError) as exc:
        cause = exc.__cause__ if isinstance(exc, ChatError) else exc
        code = getattr(cause, "code", None)
        print(f"provider_http_code={code or 'unavailable'}")
        print(f"classification={_classification(code)}")
        print(f"provider_reason={_safe_reason(cause)}")
        print("validation=failed")
        return 1


def _minimal(settings: Settings) -> tuple[bool, str | None]:
    client = genai.Client(
        api_key=settings.gemini_key_value,
        http_options=types.HttpOptions(
            api_version=settings.gemini_api_version,
            timeout=settings.chat_request_timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    try:
        response = client.models.generate_content(
            model=settings.llm_model,
            contents="Balas tepat dengan satu kata: OK",
            config=types.GenerateContentConfig(
                max_output_tokens=128,
                thinking_config=types.ThinkingConfig(thinking_budget=32, include_thoughts=False),
            ),
        )
        return bool((response.text or "").strip()), response.model_version
    finally:
        client.close()


def _structured(settings: Settings) -> tuple[bool, str | None]:
    adapter = GeminiChatAdapter(settings)
    try:
        result = adapter.generate_structured(
            prompt="Kembalikan status ok.",
            system_instruction="Ikuti schema dan kembalikan status ok.",
            response_model=ProbeResult,
            max_output_tokens=128,
            thinking_budget=32,
            temperature=0,
        )
        usage = adapter.last_usage
        return result.status == "ok", usage.model_version if usage else None
    finally:
        adapter.close()


def _classification(code: int | None) -> str:
    if code == 400:
        return "request_or_schema_invalid"
    if code == 404:
        return "model_or_endpoint_not_found"
    if code in {401, 403}:
        return "authentication_or_access_denied"
    if code == 429:
        return "quota_exhausted"
    return "provider_error"


def _safe_reason(exc: object) -> str:
    value = str(getattr(exc, "message", "provider request failed"))
    value = re.sub(r"(?i)(key=)[^&\s]+", r"\1[REDACTED]", value)
    return " ".join(value.split())[:300]


if __name__ == "__main__":
    raise SystemExit(main())
