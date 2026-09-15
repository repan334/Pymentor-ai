from __future__ import annotations

import json

import httpx
import pytest

from frontend.api_client import ApiClientError, PyMentorApiClient
from frontend.config import FrontendSettings


def _client(handler: httpx.MockTransport) -> PyMentorApiClient:
    return PyMentorApiClient(
        FrontendSettings(api_base_url="http://api.test/api/v1"), transport=handler
    )


def test_chat_preserves_none_and_empty_document_scope() -> None:
    bodies: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "insufficient_context", "answer": "x", "citations": []}
        )

    client = _client(httpx.MockTransport(respond))
    client.chat(question="q1", top_k=4, document_ids=None)
    client.chat(question="q2", top_k=4, document_ids=[])

    assert bodies[0]["document_ids"] is None
    assert bodies[1]["document_ids"] == []


def test_http_error_is_mapped_without_raw_body_or_traceback() -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "detail": {"code": "quiz_input_invalid", "message": "Semua soal wajib dijawab"},
                "debug": "postgresql://user:secret@example/db",
            },
        )

    with pytest.raises(ApiClientError) as captured:
        _client(httpx.MockTransport(respond)).get_quiz(10)

    assert captured.value.status_code == 422
    assert captured.value.code == "quiz_input_invalid"
    assert "Semua soal wajib dijawab" in str(captured.value)
    assert "postgresql" not in str(captured.value)
    assert captured.value.outcome_uncertain is False


def test_mutation_timeout_marks_outcome_uncertain_without_retry() -> None:
    calls = 0

    def timeout(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("secret transport detail", request=request)

    with pytest.raises(ApiClientError) as captured:
        _client(httpx.MockTransport(timeout)).submit_attempt(
            10,
            idempotency_key="fixed",
            payload={"answers": [{"question_id": 20, "option_id": 30}]},
        )

    assert calls == 1
    assert captured.value.outcome_uncertain is True
    assert "secret transport detail" not in str(captured.value)


def test_base_url_rejects_embedded_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BASE_URL", "http://user:secret@api.test/api/v1")
    with pytest.raises(ValueError, match="kredensial"):
        FrontendSettings.from_environment()
