import asyncio
from datetime import UTC, datetime

import pytest
from app.api.dependencies import get_document_service
from app.api.middleware import MultipartBodyLimitMiddleware
from app.core.config import Settings
from app.documents.service import (
    ChunkPage,
    ChunkView,
    DocumentNotFound,
    DocumentPage,
    DocumentView,
    IngestionResult,
)
from app.factory import create_app
from app.ingestion.models import PreparedDocument
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from tests.pdf_factory import build_blank_pdf, build_text_pdf


class MemoryDocumentService:
    def __init__(self) -> None:
        self.documents: dict[int, DocumentView] = {}
        self.chunks: dict[int, list[ChunkView]] = {}

    def ingest(self, prepared: PreparedDocument) -> IngestionResult:
        for document in self.documents.values():
            if (
                document.checksum_sha256 == prepared.extracted.checksum_sha256
                and document.extraction_profile == prepared.extracted.extraction_profile
            ):
                return IngestionResult(document=document, duplicate=True)

        document_id = len(self.documents) + 1
        timestamp = datetime.now(UTC)
        source = prepared.extracted
        document = DocumentView(
            id=document_id,
            source_name=source.source_name,
            source_type=source.source_type,
            file_size_bytes=source.file_size_bytes,
            checksum_sha256=source.checksum_sha256,
            extraction_profile=source.extraction_profile,
            status="processed",
            character_count=len(source.reference_text),
            chunk_count=len(prepared.chunks),
            reference_text=source.reference_text,
            metadata=source.metadata,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.documents[document_id] = document
        self.chunks[document_id] = [
            ChunkView(
                id=index + 1,
                document_id=document_id,
                chunk_index=chunk.index,
                content=chunk.content,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                page_number=chunk.page_number,
                metadata={**chunk.metadata, "document_id": document_id},
            )
            for index, chunk in enumerate(prepared.chunks)
        ]
        return IngestionResult(document=document, duplicate=False)

    def list_documents(self, *, limit: int, offset: int) -> DocumentPage:
        documents = sorted(self.documents.values(), key=lambda item: item.id, reverse=True)
        return DocumentPage(
            items=tuple(documents[offset : offset + limit]),
            total=len(documents),
            limit=limit,
            offset=offset,
        )

    def get_document(self, document_id: int) -> DocumentView:
        try:
            return self.documents[document_id]
        except KeyError as exc:
            raise DocumentNotFound(document_id) from exc

    def list_chunks(self, document_id: int, *, limit: int, offset: int) -> ChunkPage:
        if document_id not in self.documents:
            raise DocumentNotFound(document_id)
        chunks = self.chunks[document_id]
        return ChunkPage(
            items=tuple(chunks[offset : offset + limit]),
            total=len(chunks),
            limit=limit,
            offset=offset,
        )


class UnavailableDocumentService:
    def list_documents(self, *, limit: int, offset: int) -> DocumentPage:
        raise OperationalError("SELECT documents", {}, Exception("connection unavailable"))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=None,
        database_url_unpooled=None,
        ingestion_chunk_size=12,
        ingestion_chunk_overlap=2,
    )


@pytest.fixture
def service() -> MemoryDocumentService:
    return MemoryDocumentService()


@pytest.fixture
def client(settings: Settings, service: MemoryDocumentService) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_document_service] = lambda: service
    return TestClient(app)


def test_upload_text_persists_exact_reference_and_addressable_chunks(
    client: TestClient,
) -> None:
    text = "# Contoh\r\n```python\r\nif True:\r\n    print('ya')\r\n```\r\n"
    payload = text.encode("utf-8-sig")

    response = client.post(
        "/api/v1/documents",
        files={"file": ("materi.md", payload, "text/markdown")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["duplicate"] is False
    assert body["status"] == "processed"
    assert body["reference_text"] == text
    assert body["file_size_bytes"] == len(payload)

    chunks_response = client.get(f"/api/v1/documents/{body['id']}/chunks")
    assert chunks_response.status_code == 200
    chunks = chunks_response.json()["items"]
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert text[chunk["start_char"] : chunk["end_char"]] == chunk["content"]
        assert chunk["page_number"] is None


def test_duplicate_returns_existing_id_without_adding_chunks(
    client: TestClient,
    service: MemoryDocumentService,
) -> None:
    first = client.post(
        "/api/v1/documents",
        files={"file": ("first.txt", b"same bytes", "text/plain")},
    )
    original_chunk_count = len(service.chunks[first.json()["id"]])
    duplicate = client.post(
        "/api/v1/documents",
        files={"file": ("renamed.txt", b"same bytes", "application/octet-stream")},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["id"] == first.json()["id"]
    assert len(service.documents) == 1
    assert len(service.chunks[first.json()["id"]]) == original_chunk_count


def test_text_pdf_upload_retains_real_page_metadata(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents",
        files={
            "file": (
                "pages.pdf",
                build_text_pdf("Page one text", "Page two text"),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201
    document = response.json()
    chunks = client.get(f"/api/v1/documents/{document['id']}/chunks").json()["items"]
    assert {chunk["page_number"] for chunk in chunks} == {1, 2}
    for chunk in chunks:
        assert (
            document["reference_text"][chunk["start_char"] : chunk["end_char"]] == chunk["content"]
        )


def test_document_list_detail_and_pagination_contract(client: TestClient) -> None:
    ids = []
    for index in range(3):
        result = client.post(
            "/api/v1/documents",
            files={"file": (f"lesson-{index}.txt", f"content {index}".encode(), "text/plain")},
        )
        ids.append(result.json()["id"])

    response = client.get("/api/v1/documents?limit=2&offset=1")
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["limit"] == 2
    assert response.json()["offset"] == 1
    assert len(response.json()["items"]) == 2

    detail = client.get(f"/api/v1/documents/{ids[0]}")
    assert detail.status_code == 200
    assert detail.json()["reference_text"] == "content 0"
    assert client.get("/api/v1/documents?limit=101").status_code == 422


def test_not_found_contract_applies_to_detail_and_chunks(client: TestClient) -> None:
    for path in ("/api/v1/documents/999", "/api/v1/documents/999/chunks"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {
            "detail": {"code": "document_not_found", "message": "Document was not found"}
        }


@pytest.mark.parametrize(
    ("filename", "payload", "status_code", "code"),
    [
        ("lesson.exe", b"text", 415, "unsupported_format"),
        ("lesson.txt", b"\xff\xfe", 422, "invalid_encoding"),
        ("broken.pdf", b"%PDF-1.4\nbroken", 422, "invalid_pdf"),
        ("blank.pdf", build_blank_pdf(), 422, "no_usable_pdf_text"),
        ("empty.txt", b"", 422, "empty_document"),
        ("blank.md", b" \r\n\t", 422, "empty_document"),
    ],
)
def test_expected_upload_errors_are_safe_and_specific(
    client: TestClient,
    filename: str,
    payload: bytes,
    status_code: int,
    code: str,
) -> None:
    response = client.post(
        "/api/v1/documents",
        files={"file": (filename, payload, "application/octet-stream")},
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    assert "D:\\" not in response.text


def test_actual_file_size_and_multipart_body_have_separate_limits() -> None:
    settings = Settings(
        _env_file=None,
        max_upload_size_mb=1,
        max_multipart_body_size_mb=2,
        database_url=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_document_service] = MemoryDocumentService
    client = TestClient(app)

    file_response = client.post(
        "/api/v1/documents",
        files={"file": ("large.txt", b"a" * (1024 * 1024 + 1), "text/plain")},
    )
    body_response = client.post(
        "/api/v1/documents",
        files={"file": ("larger.txt", b"a" * (2 * 1024 * 1024), "text/plain")},
    )

    assert file_response.status_code == 413
    assert file_response.json()["detail"]["code"] == "file_too_large"
    assert body_response.status_code == 413
    assert body_response.json()["detail"]["code"] == "multipart_body_too_large"


def test_multipart_limit_counts_actual_bytes_even_with_false_content_length() -> None:
    downstream_called = False
    sent_messages = []

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_called
        downstream_called = True

    middleware = MultipartBodyLimitMiddleware(
        downstream,
        path="/api/v1/documents",
        max_bytes=5,
    )
    incoming = iter(
        [
            {"type": "http.request", "body": b"123456", "more_body": False},
        ]
    )

    async def receive():
        return next(incoming)

    async def send(message) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/documents",
        "raw_path": b"/api/v1/documents",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-length", b"1")],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
    }

    asyncio.run(middleware(scope, receive, send))

    assert downstream_called is False
    assert sent_messages[0]["status"] == 413
    assert b"multipart_body_too_large" in sent_messages[1]["body"]


def test_exactly_one_file_is_required(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents",
        files=[
            ("file", ("one.txt", b"one", "text/plain")),
            ("file", ("two.txt", b"two", "text/plain")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "one_file_required"


def test_database_failure_maps_only_sqlalchemy_errors_to_safe_503(
    settings: Settings,
) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_document_service] = UnavailableDocumentService
    response = TestClient(app).get("/api/v1/documents")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "database_unavailable",
            "message": "Document storage is temporarily unavailable",
        }
    }
    assert "connection unavailable" not in response.text


def test_document_routes_and_documented_errors_are_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/documents" in schema["paths"]
    assert "/api/v1/documents/{document_id}" in schema["paths"]
    assert "/api/v1/documents/{document_id}/chunks" in schema["paths"]
    upload_responses = schema["paths"]["/api/v1/documents"]["post"]["responses"]
    assert {"200", "201", "413", "415", "422", "503"} <= set(upload_responses)
    assert (
        "multipart/form-data"
        in schema["paths"]["/api/v1/documents"]["post"]["requestBody"]["content"]
    )
