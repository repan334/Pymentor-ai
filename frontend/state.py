from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

DocumentScope = Literal["Semua dokumen siap", "Pilih dokumen tertentu", "Tanpa dokumen"]


def resolve_document_scope(mode: DocumentScope, selected_ids: Sequence[int]) -> list[int] | None:
    if mode == "Semua dokumen siap":
        return None
    if mode == "Tanpa dokumen":
        return []
    return list(dict.fromkeys(selected_ids))


def build_answer_payload(
    quiz: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, list[dict[str, int]]]:
    answers: list[dict[str, int]] = []
    quiz_id = int(quiz["id"])
    for question in quiz["questions"]:
        question_id = int(question["id"])
        selected = state.get(answer_widget_key(quiz_id, question_id))
        if selected is None:
            raise ValueError("Semua pertanyaan harus dijawab sebelum dikirim.")
        answers.append({"question_id": question_id, "option_id": int(selected)})
    return {"answers": answers}


def answer_widget_key(quiz_id: int, question_id: int) -> str:
    return f"quiz_answer_{quiz_id}_{question_id}"


@dataclass(frozen=True, slots=True)
class PendingSubmission:
    quiz_id: int
    idempotency_key: str
    payload: dict[str, Any]


def prepare_submission(
    state: MutableMapping[str, Any], *, quiz_id: int, payload: dict[str, Any]
) -> PendingSubmission:
    existing = state.get("pending_quiz_submission")
    if isinstance(existing, PendingSubmission) and existing.quiz_id == quiz_id:
        return existing
    pending = PendingSubmission(
        quiz_id=quiz_id,
        idempotency_key=f"streamlit-{uuid4()}",
        payload=payload,
    )
    state["pending_quiz_submission"] = pending
    return pending


def finish_submission(state: MutableMapping[str, Any], result: dict[str, Any]) -> None:
    state["quiz_result"] = result
    state.pop("pending_quiz_submission", None)


def abandon_pending_submission(state: MutableMapping[str, Any]) -> None:
    state.pop("pending_quiz_submission", None)
