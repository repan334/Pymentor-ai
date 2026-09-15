from __future__ import annotations

from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from frontend.api_client import ApiClientError
from frontend.state import answer_widget_key


def _document(*, document_id: int = 2, ready: bool = True) -> dict[str, Any]:
    return {
        "id": document_id,
        "source_name": "fungsi.md",
        "source_type": "md",
        "file_size_bytes": 120,
        "checksum_sha256": "a" * 64,
        "extraction_profile": "markdown-utf8-v1",
        "status": "processed",
        "indexing_status": "ready" if ready else "not_indexed",
        "character_count": 48,
        "chunk_count": 1,
        "created_at": "2026-09-14T00:00:00Z",
        "updated_at": "2026-09-14T00:00:00Z",
    }


def _quiz() -> dict[str, Any]:
    return {
        "id": 10,
        "topic_id": "python-functions",
        "topic": "Fungsi Python",
        "question_count": 1,
        "questions": [
            {
                "id": 20,
                "question": "Apa hasil fungsi tanpa return eksplisit?",
                "options": [
                    {"id": 30, "text": "None"},
                    {"id": 31, "text": "0"},
                    {"id": 32, "text": "False"},
                    {"id": 33, "text": "Error"},
                ],
            }
        ],
        "created_at": "2026-09-14T00:00:00Z",
    }


def _attempt() -> dict[str, Any]:
    return {
        "id": 40,
        "quiz_id": 10,
        "correct_count": 1,
        "question_count": 1,
        "percentage": 100.0,
        "review": [
            {
                "question_id": 20,
                "selected_option_id": 30,
                "correct_option_id": 30,
                "is_correct": True,
                "explanation": "Materi menjelaskan hasilnya adalah None.",
                "sources": [
                    {
                        "reference_id": "S1",
                        "document_id": 2,
                        "chunk_id": 5,
                        "source_name": "fungsi.md",
                        "start_char": 0,
                        "end_char": 48,
                        "excerpt": "Fungsi tanpa return eksplisit menghasilkan None.",
                        "page_number": None,
                        "metadata": {},
                    }
                ],
            }
        ],
        "created_at": "2026-09-14T00:00:00Z",
        "idempotent_replay": False,
    }


class FakeApi:
    def __init__(self) -> None:
        self.mutations: list[tuple[str, dict[str, Any]]] = []
        self.submission_calls: list[tuple[str, dict[str, Any]]] = []
        self.timeout_first_submission = False

    def list_documents(self, **_: Any) -> dict[str, Any]:
        return {"items": [_document()], "total": 1, "limit": 100, "offset": 0}

    def upload_document(self, **kwargs: Any) -> dict[str, Any]:
        self.mutations.append(("upload", kwargs))
        return {**_document(ready=False), "duplicate": False, "reference_text": "x", "metadata": {}}

    def index_document(self, document_id: int) -> dict[str, Any]:
        self.mutations.append(("index", {"document_id": document_id}))
        return {"document_id": document_id, "idempotent": False}

    def get_index_status(self, document_id: int) -> dict[str, Any]:
        return {"document_id": document_id, "indexing_status": "ready"}

    def get_document(self, document_id: int) -> dict[str, Any]:
        return {
            **_document(document_id=document_id),
            "reference_text": "return None",
            "metadata": {},
        }

    def list_chunks(self, document_id: int, **_: Any) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": 5,
                    "document_id": document_id,
                    "chunk_index": 0,
                    "content": "return None",
                    "start_char": 0,
                    "end_char": 11,
                    "page_number": None,
                    "metadata": {},
                }
            ],
            "total": 1,
            "limit": 10,
            "offset": 0,
        }

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.mutations.append(("chat", kwargs))
        return {
            "status": "answered",
            "answer": "Gunakan `return`. [S1]",
            "citations": [
                {
                    "reference_id": "S1",
                    "document_id": 2,
                    "chunk_id": 5,
                    "source_name": "fungsi.md",
                    "start_char": 0,
                    "end_char": 11,
                    "excerpt": "return None",
                    "page_number": None,
                }
            ],
        }

    def list_topics(self, **_: Any) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": "python-functions",
                    "display_name": "Fungsi Python",
                    "description": None,
                    "created_at": "2026-09-14T00:00:00Z",
                    "updated_at": "2026-09-14T00:00:00Z",
                    "legacy_quizzes_assigned": 0,
                }
            ],
            "total": 1,
            "limit": 100,
            "offset": 0,
        }

    def create_topic(self, **kwargs: Any) -> dict[str, Any]:
        self.mutations.append(("topic", kwargs))
        return {"id": kwargs["topic_id"], "display_name": kwargs["display_name"]}

    def list_quizzes(self, **kwargs: Any) -> dict[str, Any]:
        items = (
            []
            if kwargs.get("unassigned")
            else [{key: value for key, value in _quiz().items() if key != "questions"}]
        )
        return {"items": items, "total": len(items), "limit": 100, "offset": 0}

    def get_quiz(self, quiz_id: int) -> dict[str, Any]:
        assert quiz_id == 10
        return _quiz()

    def create_quiz(self, **kwargs: Any) -> dict[str, Any]:
        self.mutations.append(("create_quiz", kwargs))
        return _quiz()

    def submit_attempt(
        self, quiz_id: int, *, idempotency_key: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        assert quiz_id == 10
        self.submission_calls.append((idempotency_key, payload))
        if self.timeout_first_submission and len(self.submission_calls) == 1:
            raise ApiClientError("Timeout aman", outcome_uncertain=True)
        return _attempt()

    def list_attempts(self, **_: Any) -> dict[str, Any]:
        item = {
            key: value
            for key, value in _attempt().items()
            if key not in {"review", "idempotent_replay"}
        }
        return {"items": [item], "total": 1, "limit": 100, "offset": 0}

    def get_attempt(self, attempt_id: int) -> dict[str, Any]:
        assert attempt_id == 40
        return _attempt()

    def get_topic_progress(self, topic_id: str) -> dict[str, Any]:
        return {
            "topic_id": topic_id,
            "topic_name": "Fungsi Python",
            "score": None,
            "counted_questions": 0,
            "counted_quizzes": 0,
            "recommendation": "insufficient_evidence",
            "message": "Belum cukup soal.",
        }

    def assign_quiz_topic(self, quiz_id: int, topic_id: str) -> dict[str, Any]:
        self.mutations.append(("assign", {"quiz_id": quiz_id, "topic_id": topic_id}))
        return {"quiz_id": quiz_id, "topic_id": topic_id, "changed": True}


def _app(fake: FakeApi) -> AppTest:
    entrypoint = Path(__file__).parents[3] / "frontend" / "app.py"
    app = AppTest.from_file(entrypoint, default_timeout=10)
    app.session_state["_api_client"] = fake
    return app.run()


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(item for item in app.button if item.label == label)


def _radio(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(item for item in app.radio if item.label == label)


def test_plain_rerun_does_not_trigger_mutations_and_empty_progress_renders() -> None:
    fake = FakeApi()
    app = _app(fake)

    assert not app.exception
    app.run()
    assert fake.mutations == []

    app.sidebar.radio[0].set_value("Progres").run()
    assert any(metric.value == "Belum ada" for metric in app.metric)
    assert fake.mutations == []


def test_tutor_preserves_empty_scope_and_renders_answer_source() -> None:
    fake = FakeApi()
    app = _app(fake)
    app.sidebar.radio[0].set_value("Tutor").run()
    _radio(app, "Cakupan materi").set_value("Tanpa dokumen").run()
    app.text_area[0].input("Apa fungsi return?")
    _button(app, "Tanya tutor").click().run()

    assert fake.mutations[-1][0] == "chat"
    assert fake.mutations[-1][1]["document_ids"] == []
    assert any("Gunakan `return`" in markdown.value for markdown in app.markdown)
    assert any(expander.label.startswith("S1") for expander in app.expander)


def test_quiz_draft_survives_navigation_and_uncertain_submit_replays_exact_payload() -> None:
    fake = FakeApi()
    fake.timeout_first_submission = True
    app = _app(fake)
    app.sidebar.radio[0].set_value("Kuis").run()
    _button(app, "Buka quiz").click().run()
    answer = _radio(app, "Jawaban soal 1")
    answer.set_value(30).run()

    app.sidebar.radio[0].set_value("Tutor").run()
    app.sidebar.radio[0].set_value("Kuis").run()
    assert app.session_state[answer_widget_key(10, 20)] == 30

    _button(app, "Kirim jawaban").click().run()
    assert len(fake.submission_calls) == 1
    app.run()
    _button(app, "Kirim ulang jawaban yang sama").click().run()

    assert len(fake.submission_calls) == 2
    assert fake.submission_calls[0] == fake.submission_calls[1]
    assert any(metric.value == "100.00%" for metric in app.metric)
    assert any("Materi menjelaskan" in text.value for text in app.markdown)
