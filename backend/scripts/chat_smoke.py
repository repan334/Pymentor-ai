"""Validate one live Gemini chat response without printing prompts or secrets."""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.chat.gemini import GeminiChatAdapter  # noqa: E402
from app.chat.models import ChatError, TutorSource  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    adapter = GeminiChatAdapter(settings)
    output_status: str | None = None
    error_code: str | None = None
    valid = False
    try:
        output = adapter.generate(
            question="Apa nilai yang dikembalikan fungsi pada materi?",
            sources=[
                TutorSource(
                    reference_id="S1",
                    document_id=1,
                    chunk_id=1,
                    source_name="smoke.txt",
                    start_char=0,
                    end_char=33,
                    excerpt="Fungsi contoh mengembalikan nilai 42.",
                    page_number=None,
                )
            ],
        )
        output_status = output.status
        valid = output.status in {"answered", "insufficient_context"}
    except ChatError as exc:
        error_code = exc.code
        provider_code = getattr(exc.__cause__, "code", None)
        if provider_code is not None:
            print(f"provider_http_code={provider_code}")
    finally:
        adapter.close()

    print(f"provider={settings.llm_provider}")
    print(f"model={settings.llm_model}")
    print(f"prompt_version={settings.llm_prompt_version}")
    print(f"output_status={output_status or 'unavailable'}")
    print(f"validation={'passed' if valid else 'failed'}")
    if error_code is not None:
        print(f"error={error_code}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
