from __future__ import annotations

from frontend.state import (
    PendingSubmission,
    answer_widget_key,
    build_answer_payload,
    finish_submission,
    prepare_submission,
    resolve_document_scope,
)


def test_document_scope_distinguishes_all_selected_and_none() -> None:
    assert resolve_document_scope("Semua dokumen siap", [1, 2]) is None
    assert resolve_document_scope("Pilih dokumen tertentu", [2, 2, 1]) == [2, 1]
    assert resolve_document_scope("Pilih dokumen tertentu", []) == []
    assert resolve_document_scope("Tanpa dokumen", [1]) == []


def test_draft_answers_build_complete_payload_without_exposing_key() -> None:
    quiz = {
        "id": 10,
        "questions": [
            {"id": 20, "options": [{"id": 30}, {"id": 31}]},
            {"id": 21, "options": [{"id": 32}, {"id": 33}]},
        ],
    }
    state = {
        answer_widget_key(10, 20): 30,
        answer_widget_key(10, 21): 33,
    }

    assert build_answer_payload(quiz, state) == {
        "answers": [
            {"question_id": 20, "option_id": 30},
            {"question_id": 21, "option_id": 33},
        ]
    }


def test_uncertain_submission_reuses_exact_key_and_payload_then_new_attempt_gets_new_key() -> None:
    state: dict[str, object] = {}
    first_payload = {"answers": [{"question_id": 20, "option_id": 30}]}
    first = prepare_submission(state, quiz_id=10, payload=first_payload)
    replay = prepare_submission(
        state,
        quiz_id=10,
        payload={"answers": [{"question_id": 20, "option_id": 31}]},
    )

    assert isinstance(first, PendingSubmission)
    assert replay.idempotency_key == first.idempotency_key
    assert replay.payload == first_payload

    finish_submission(state, {"id": 40})
    second = prepare_submission(state, quiz_id=10, payload=first_payload)
    assert second.idempotency_key != first.idempotency_key
    assert state["quiz_result"] == {"id": 40}
