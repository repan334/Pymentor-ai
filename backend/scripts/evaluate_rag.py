"""Run the frozen RAG evaluation against unique Neon fixtures and Gemini.

Evaluation keys are read only after each answer and are never sent to retrieval or
generation. The output intentionally marks semantic grading for human review.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.chat.gemini import GeminiChatAdapter  # noqa: E402
from app.chat.models import ChatAuthenticationError, ChatError, ChatQuotaError  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.db.session import create_database_engine  # noqa: E402
from app.documents.service import DocumentService  # noqa: E402
from app.embeddings.gemini import GeminiEmbeddingAdapter  # noqa: E402
from app.embeddings.models import (  # noqa: E402
    DocumentEmbeddingInput,
    EmbeddingAuthenticationError,
    EmbeddingError,
    EmbeddingQuotaError,
)
from app.ingestion.pipeline import prepare_document  # noqa: E402
from app.rag.service import RagTutorService  # noqa: E402
from app.retrieval.service import IndexingService, SearchService  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

EVALUATION = ROOT / "evaluation" / "v1"


class CountingEmbedding:
    def __init__(self, adapter: GeminiEmbeddingAdapter) -> None:
        self.adapter = adapter
        self.profile = adapter.profile
        self.calls = 0

    def embed_documents(self, inputs: list[DocumentEmbeddingInput]) -> list[list[float]]:
        self.calls += 1
        return self.adapter.embed_documents(inputs)

    def embed_query(self, query: str) -> list[float]:
        self.calls += 1
        return self.adapter.embed_query(query)


class TimedSearch:
    def __init__(self, service: SearchService) -> None:
        self.service = service
        self.last_seconds = 0.0

    def search(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return self.service.search(**kwargs)
        finally:
            self.last_seconds = time.perf_counter() - started


class TimedChat:
    def __init__(self, adapter: GeminiChatAdapter) -> None:
        self.adapter = adapter
        self.profile = adapter.profile
        self.calls = 0
        self.last_seconds = 0.0

    def generate(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        self.calls += 1
        try:
            return self.adapter.generate(**kwargs)
        finally:
            self.last_seconds = time.perf_counter() - started


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index] * 1000, 2)


def _prepare(settings: Settings, filename: str, data: bytes) -> Any:
    return prepare_document(
        data,
        filename=filename,
        max_pdf_pages=settings.max_pdf_pages,
        max_characters=settings.max_extracted_characters,
        chunk_size=settings.ingestion_chunk_size,
        chunk_overlap=settings.ingestion_chunk_overlap,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default=str(ROOT / "evaluation" / "results" / "phase7-live.json")
    )
    parser.add_argument("--max-cases", type=int, default=16)
    args = parser.parse_args()
    if not 1 <= args.max_cases <= 16:
        parser.error("--max-cases must be between 1 and 16")
    settings = Settings().model_copy(update={"embedding_max_attempts": 1, "chat_max_attempts": 1})
    token = uuid.uuid4().hex
    engine = create_database_engine(settings)
    embedding_raw = GeminiEmbeddingAdapter(settings)
    embedding = CountingEmbedding(embedding_raw)
    chat_raw = GeminiChatAdapter(settings)
    chat = TimedChat(chat_raw)
    created_checksums: list[str] = []
    document_ids: dict[str, int] = {}
    source_names: dict[int, str] = {}
    results: list[dict[str, Any]] = []
    started_all = time.perf_counter()
    stopped_reason: str | None = None
    try:
        with Session(engine, expire_on_commit=False) as session:
            for path in sorted((EVALUATION / "corpus").glob("*.md")):
                data = path.read_bytes() + f"\n<!-- run:{token} -->\n".encode()
                prepared = _prepare(settings, f"eval-{path.stem}-{token}.md", data)
                ingestion = DocumentService(session).ingest(prepared)
                if not ingestion.duplicate:
                    created_checksums.append(ingestion.document.checksum_sha256)
                document_ids[path.name] = ingestion.document.id
                source_names[ingestion.document.id] = path.name
                IndexingService(session, embedding, settings).index_document(ingestion.document.id)

            case_plan = [
                (split, case)
                for split in ("development", "holdout")
                for case in _load(EVALUATION / f"{split}.json")["cases"]
            ][: args.max_cases]
            for split, case in case_plan:
                scope = [document_ids[name] for name in case["document_scope"]]
                timed_search = TimedSearch(SearchService(session, embedding, settings))
                service = RagTutorService(timed_search, chat, settings)
                generation_calls_before = chat.calls
                started = time.perf_counter()
                try:
                    response = service.answer(
                        question=case["question"], top_k=4, document_ids=scope
                    )
                except (ChatError, EmbeddingError) as exc:
                    total_seconds = time.perf_counter() - started
                    results.append(
                        _error_case_result(
                            split=split,
                            case=case,
                            error_code=exc.code,
                            retrieval_seconds=timed_search.last_seconds,
                            generation_seconds=(
                                chat.last_seconds if chat.calls > generation_calls_before else 0.0
                            ),
                            total_seconds=total_seconds,
                        )
                    )
                    if isinstance(
                        exc,
                        (
                            ChatAuthenticationError,
                            ChatQuotaError,
                            EmbeddingAuthenticationError,
                            EmbeddingQuotaError,
                        ),
                    ):
                        stopped_reason = exc.code
                        break
                    continue
                total_seconds = time.perf_counter() - started
                generation_seconds = (
                    chat.last_seconds if chat.calls > generation_calls_before else 0.0
                )
                cited_aliases = [
                    source_names[citation.document_id] for citation in response.citations
                ]
                allowed_ids = set(scope)
                results.append(
                    {
                        "case_id": case["case_id"],
                        "split": split,
                        "category": case["category"],
                        "expected_status": case["expected_status"],
                        "actual_status": response.status,
                        "answer": response.answer,
                        "citation_sources": cited_aliases,
                        "objective": {
                            "request_succeeded": True,
                            "status_matches": response.status == case["expected_status"],
                            "citations_within_scope": all(
                                citation.document_id in allowed_ids
                                for citation in response.citations
                            ),
                            "source_subset_valid": set(cited_aliases)
                            <= set(case["document_scope"]),
                        },
                        "semantic_review": "needs_manual_review",
                        "required_points": case["required_points"],
                        "forbidden_points": case["forbidden_points"],
                        "rationale": case["rationale"],
                        "latency_ms": {
                            "retrieval": round(timed_search.last_seconds * 1000, 2),
                            "generation": round(generation_seconds * 1000, 2),
                            "total": round(total_seconds * 1000, 2),
                        },
                        "token_usage": _usage(chat_raw),
                    }
                )
    except (ChatError, EmbeddingError) as exc:
        stopped_reason = exc.code
    finally:
        with engine.begin() as connection:
            if created_checksums:
                connection.execute(
                    delete(Document).where(Document.checksum_sha256.in_(created_checksums))
                )
        chat_raw.close()
        embedding_raw.close()
        engine.dispose()

    latencies = [item["latency_ms"]["total"] / 1000 for item in results]
    report = {
        "evaluation_version": "rag-eval-v1",
        "model": settings.llm_model,
        "tutor_prompt_version": settings.llm_prompt_version,
        "completed_cases": len(results),
        "planned_cases": 16,
        "scheduled_cases": args.max_cases,
        "unrun_cases": 16 - len(results),
        "stopped_reason": stopped_reason,
        "provider_calls": {
            "inference_total": embedding.calls + chat.calls,
            "embedding": embedding.calls,
            "generation": chat.calls,
            "retry": 0,
            "discovery": 0,
        },
        "latency": {
            "samples": len(latencies),
            "method": "nearest-rank over end-to-end case latency",
            "p50_ms": _percentile(latencies, 0.50),
            "p95_ms": _percentile(latencies, 0.95),
            "small_sample_warning": True,
        },
        "elapsed_seconds": round(time.perf_counter() - started_all, 2),
        "cases": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"completed_cases={len(results)}/16")
    print(f"inference_calls={embedding.calls + chat.calls}")
    print(f"stopped_reason={stopped_reason or 'none'}")
    print(f"result={output}")
    succeeded = sum(item["objective"]["request_succeeded"] for item in results)
    print(f"successful_requests={succeeded}/{len(results)}")
    return 0 if len(results) == args.max_cases and stopped_reason is None else 1


def _error_case_result(
    *,
    split: str,
    case: dict[str, Any],
    error_code: str,
    retrieval_seconds: float,
    generation_seconds: float,
    total_seconds: float,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "split": split,
        "category": case["category"],
        "expected_status": case["expected_status"],
        "actual_status": None,
        "answer": None,
        "citation_sources": [],
        "error_code": error_code,
        "objective": {
            "request_succeeded": False,
            "status_matches": False,
            "citations_within_scope": True,
            "source_subset_valid": True,
        },
        "semantic_review": "not_gradable",
        "required_points": case["required_points"],
        "forbidden_points": case["forbidden_points"],
        "rationale": case["rationale"],
        "latency_ms": {
            "retrieval": round(retrieval_seconds * 1000, 2),
            "generation": round(generation_seconds * 1000, 2),
            "total": round(total_seconds * 1000, 2),
        },
        "token_usage": {
            "model_version": None,
            "prompt_tokens": None,
            "output_tokens": None,
            "thinking_tokens": None,
        },
    }


def _usage(adapter: GeminiChatAdapter) -> dict[str, int | str | None]:
    usage = adapter.last_usage
    if usage is None:
        return {
            "model_version": None,
            "prompt_tokens": None,
            "output_tokens": None,
            "thinking_tokens": None,
        }
    return {
        "model_version": usage.model_version,
        "prompt_tokens": usage.prompt_tokens,
        "output_tokens": usage.output_tokens,
        "thinking_tokens": usage.thinking_tokens,
    }


if __name__ == "__main__":
    raise SystemExit(main())
