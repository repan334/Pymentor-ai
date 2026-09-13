"""Exercise a running API over HTTP and clean only this script's unique fixture."""

import json
import os
import sys
import time
import uuid
from hashlib import sha256
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.models import Document  # noqa: E402
from app.db.session import create_database_engine  # noqa: E402
from sqlalchemy import delete  # noqa: E402


def main() -> int:
    base_url = os.getenv("PYMENTOR_SMOKE_BASE_URL", "http://127.0.0.1:8000")
    token = uuid.uuid4().hex
    content = f"HTTP Phase 5 fixture {token}. A Python function returns a value."
    checksum = sha256(content.encode()).hexdigest()
    engine = create_database_engine()
    try:
        with httpx.Client(base_url=base_url, timeout=30) as client:
            for _ in range(20):
                try:
                    if client.get("/api/v1/health").status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("API did not become healthy")

            upload = client.post(
                "/api/v1/documents",
                files={"file": ("phase-5-http.txt", content.encode(), "text/plain")},
            )
            upload.raise_for_status()
            document_id = upload.json()["id"]
            indexed = client.post(f"/api/v1/documents/{document_id}/index")
            indexed.raise_for_status()
            repeated = client.post(f"/api/v1/documents/{document_id}/index")
            repeated.raise_for_status()
            status = client.get(f"/api/v1/documents/{document_id}/index-status")
            status.raise_for_status()
            search = client.post(
                "/api/v1/search",
                json={
                    "query": "How does a Python function return a value?",
                    "top_k": 3,
                    "document_ids": [document_id],
                },
            )
            search.raise_for_status()

        hit = search.json()["results"][0]
        print(
            json.dumps(
                {
                    "upload_status": upload.status_code,
                    "document_id": document_id,
                    "index_status": indexed.status_code,
                    "indexing_status": indexed.json()["indexing_status"],
                    "repeat_idempotent": repeated.json()["idempotent"],
                    "eligible_for_search": status.json()["eligible_for_search"],
                    "search_status": search.status_code,
                    "result_count": len(search.json()["results"]),
                    "first_hit": {
                        "chunk_id": hit["chunk_id"],
                        "document_id": hit["document_id"],
                        "source_name": hit["source_name"],
                        "start_char": hit["start_char"],
                        "end_char": hit["end_char"],
                        "page_number": hit["page_number"],
                        "cosine_distance": hit["cosine_distance"],
                    },
                },
                indent=2,
            )
        )
        return 0
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Document).where(Document.checksum_sha256 == checksum))
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
