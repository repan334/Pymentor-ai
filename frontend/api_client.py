from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from frontend.config import FrontendSettings


class ApiClientError(RuntimeError):
    """A safe, user-facing representation of an API or transport failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "api_unavailable",
        outcome_uncertain: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.outcome_uncertain = outcome_uncertain


_STATUS_MESSAGES = {
    400: "Permintaan ditolak oleh API.",
    404: "Data yang diminta tidak ditemukan.",
    409: "Permintaan bertentangan dengan data yang sudah tersimpan.",
    413: "File melebihi batas ukuran upload.",
    415: "Format file tidak didukung.",
    422: "Input belum valid atau materi tidak mencukupi.",
    429: "Kuota penyedia sedang habis. Coba lagi setelah kuota tersedia.",
    502: "Penyedia menghasilkan respons yang tidak dapat divalidasi.",
    503: "Layanan backend atau penyedia sedang tidak tersedia.",
}


class PyMentorApiClient:
    """The frontend's only gateway to PyMentor business operations."""

    def __init__(
        self,
        settings: FrontendSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=settings.write_timeout_seconds,
            pool=settings.connect_timeout_seconds,
        )
        self._client = httpx.Client(
            base_url=settings.api_base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def upload_document(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/documents",
            mutation=True,
            files={"file": (filename, content, content_type or "application/octet-stream")},
        )

    def list_documents(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._request("GET", "/documents", params={"limit": limit, "offset": offset})

    def get_document(self, document_id: int) -> dict[str, Any]:
        return self._request("GET", f"/documents/{document_id}")

    def list_chunks(
        self, document_id: int, *, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/documents/{document_id}/chunks",
            params={"limit": limit, "offset": offset},
        )

    def index_document(self, document_id: int) -> dict[str, Any]:
        return self._request("POST", f"/documents/{document_id}/index", mutation=True)

    def get_index_status(self, document_id: int) -> dict[str, Any]:
        return self._request("GET", f"/documents/{document_id}/index-status")

    def chat(
        self,
        *,
        question: str,
        top_k: int,
        document_ids: Sequence[int] | None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/chat",
            mutation=True,
            json={"question": question, "top_k": top_k, "document_ids": document_ids},
        )

    def create_topic(
        self, *, topic_id: str, display_name: str, description: str | None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/topics",
            mutation=True,
            json={"id": topic_id, "display_name": display_name, "description": description},
        )

    def list_topics(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._request("GET", "/topics", params={"limit": limit, "offset": offset})

    def get_topic_progress(self, topic_id: str) -> dict[str, Any]:
        return self._request("GET", f"/topics/{topic_id}/progress")

    def assign_quiz_topic(self, quiz_id: int, topic_id: str) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/quizzes/{quiz_id}/topic",
            mutation=True,
            json={"topic_id": topic_id},
        )

    def create_quiz(
        self,
        *,
        topic_id: str,
        topic: str,
        document_ids: Sequence[int] | None,
        question_count: int,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/quizzes",
            mutation=True,
            json={
                "topic_id": topic_id,
                "topic": topic,
                "document_ids": document_ids,
                "question_count": question_count,
            },
        )

    def list_quizzes(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        topic_id: str | None = None,
        unassigned: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset, "unassigned": unassigned}
        if topic_id is not None:
            params["topic_id"] = topic_id
        return self._request("GET", "/quizzes", params=params)

    def get_quiz(self, quiz_id: int) -> dict[str, Any]:
        return self._request("GET", f"/quizzes/{quiz_id}")

    def submit_attempt(
        self,
        quiz_id: int,
        *,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/quizzes/{quiz_id}/attempts",
            mutation=True,
            headers={"Idempotency-Key": idempotency_key},
            json=dict(payload),
        )

    def list_attempts(
        self, *, limit: int = 100, offset: int = 0, quiz_id: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if quiz_id is not None:
            params["quiz_id"] = quiz_id
        return self._request("GET", "/quiz-attempts", params=params)

    def get_attempt(self, attempt_id: int) -> dict[str, Any]:
        return self._request("GET", f"/quiz-attempts/{attempt_id}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        mutation: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            if mutation:
                raise ApiClientError(
                    "Waktu tunggu habis. Hasil operasi belum dapat dipastikan; gunakan tombol coba "
                    "lagi agar frontend mengirim ulang payload yang sama.",
                    code="request_timeout",
                    outcome_uncertain=True,
                ) from exc
            raise ApiClientError(
                "Waktu tunggu API habis. Periksa apakah backend masih berjalan.",
                code="request_timeout",
            ) from exc
        except httpx.RequestError as exc:
            raise ApiClientError(
                "Tidak dapat terhubung ke API. Pastikan server FastAPI berjalan di alamat "
                "konfigurasi.",
                code="api_unreachable",
                outcome_uncertain=mutation,
            ) from exc

        if response.is_error:
            code, server_message = _safe_error_detail(response)
            base_message = _STATUS_MESSAGES.get(
                response.status_code, "API tidak dapat menyelesaikan permintaan."
            )
            message = f"{base_message} ({server_message})" if server_message else base_message
            raise ApiClientError(
                message,
                status_code=response.status_code,
                code=code,
                outcome_uncertain=False,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiClientError(
                "API mengembalikan respons yang tidak dapat dibaca.",
                status_code=response.status_code,
                code="invalid_api_response",
            ) from exc
        if not isinstance(payload, dict):
            raise ApiClientError(
                "API mengembalikan bentuk data yang tidak sesuai.",
                status_code=response.status_code,
                code="invalid_api_response",
            )
        return payload


def _safe_error_detail(response: httpx.Response) -> tuple[str, str | None]:
    try:
        payload = response.json()
    except ValueError:
        return "api_error", None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        return "api_error", None
    code = detail.get("code")
    message = detail.get("message")
    safe_code = code if isinstance(code, str) and len(code) <= 100 else "api_error"
    safe_message = message if isinstance(message, str) and len(message) <= 300 else None
    return safe_code, safe_message
