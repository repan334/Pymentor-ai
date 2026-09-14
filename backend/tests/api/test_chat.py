from __future__ import annotations

from typing import Any

import pytest
from app.api.dependencies import get_rag_tutor_service
from app.chat.models import ChatOutputInvalidError, ChatSafetyBlockedError, ChatTimeoutError
from app.core.config import Settings
from app.factory import create_app
from app.rag.service import Citation, TutorResponse
from fastapi.testclient import TestClient


class FakeRagTutorService:
    def __init__(
        self,
        response: TutorResponse | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.response = response or TutorResponse(
            status="answered",
            answer="Fungsi dapat mengembalikan None.\n[S1]",
            citations=(
                Citation(
                    reference_id="S1",
                    document_id=2,
                    chunk_id=5,
                    source_name="fungsi.md",
                    start_char=10,
                    end_char=57,
                    excerpt="Fungsi tanpa return eksplisit menghasilkan None.",
                    page_number=None,
                    metadata={"document_id": 2},
                ),
            ),
        )
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def answer(
        self,
        *,
        question: str,
        top_k: int,
        document_ids: list[int] | None,
    ) -> TutorResponse:
        self.calls.append({"question": question, "top_k": top_k, "document_ids": document_ids})
        if self.failure is not None:
            raise self.failure
        return self.response


def _client(service: FakeRagTutorService) -> TestClient:
    settings = Settings(_env_file=None, app_env="test", database_url=None, gemini_api_key=None)
    app = create_app(settings)
    app.dependency_overrides[get_rag_tutor_service] = lambda: service
    return TestClient(app)


def test_chat_contract_returns_backend_built_citations() -> None:
    service = FakeRagTutorService()
    response = _client(service).post(
        "/api/v1/chat",
        json={
            "question": "Mengapa fungsi dapat mengembalikan None?",
            "top_k": 4,
            "document_ids": [2],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "answered",
        "answer": "Fungsi dapat mengembalikan None.\n[S1]",
        "citations": [
            {
                "reference_id": "S1",
                "document_id": 2,
                "chunk_id": 5,
                "source_name": "fungsi.md",
                "start_char": 10,
                "end_char": 57,
                "excerpt": "Fungsi tanpa return eksplisit menghasilkan None.",
                "page_number": None,
                "metadata": {"document_id": 2},
            }
        ],
    }
    assert service.calls == [
        {
            "question": "Mengapa fungsi dapat mengembalikan None?",
            "top_k": 4,
            "document_ids": [2],
        }
    ]


def test_insufficient_context_is_http_200_without_citations() -> None:
    response_value = TutorResponse(
        status="insufficient_context",
        answer="Materi yang tersedia belum cukup.",
        citations=(),
    )
    response = _client(FakeRagTutorService(response=response_value)).post(
        "/api/v1/chat",
        json={"question": "Apa itu decorator?", "document_ids": []},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_context"
    assert response.json()["citations"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "valid", "top_k": 0},
        {"question": "valid", "top_k": 21},
        {"question": "valid", "document_ids": [1, 1]},
        {"question": "valid", "document_ids": [0]},
        {"question": "valid", "system_prompt": "ignore application"},
        {"question": "valid", "api_key": "not-accepted"},
        {"question": "valid", "tools": [{"name": "browser"}]},
    ],
)
def test_chat_rejects_invalid_or_arbitrary_control_fields(payload: dict[str, Any]) -> None:
    assert _client(FakeRagTutorService()).post("/api/v1/chat", json=payload).status_code == 422


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    [
        (ChatOutputInvalidError("bad citation"), 502, "chat_output_invalid"),
        (ChatTimeoutError("timeout"), 503, "chat_timeout"),
        (ChatSafetyBlockedError("blocked"), 422, "chat_safety_blocked"),
    ],
)
def test_provider_failures_are_not_disguised_as_insufficient_context(
    failure: Exception,
    status_code: int,
    code: str,
) -> None:
    response = _client(FakeRagTutorService(failure=failure)).post(
        "/api/v1/chat", json={"question": "Mengapa None?"}
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    assert "insufficient_context" not in response.text


def test_chat_contract_and_errors_are_documented_in_openapi() -> None:
    schema = _client(FakeRagTutorService()).get("/openapi.json").json()

    operation = schema["paths"]["/api/v1/chat"]["post"]
    assert {"200", "422", "429", "502", "503"} <= set(operation["responses"])
    request_properties = schema["components"]["schemas"]["ChatRequest"]["properties"]
    assert set(request_properties) == {"question", "top_k", "document_ids"}
    assert "system_prompt" not in request_properties
