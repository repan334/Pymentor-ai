from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.chat.models import (
    ChatAdapter,
    ChatOutputInvalidError,
    ModelTutorOutput,
    TutorSource,
)
from app.core.config import Settings
from app.retrieval.service import SearchHit, SearchService

INSUFFICIENT_CONTEXT_ANSWER = (
    "Materi yang tersedia belum cukup untuk menjawab pertanyaan ini. "
    "Unggah atau indeks materi yang relevan, lalu coba lagi."
)
_CITATION_MARKER = re.compile(r"\[S\d+\]")


class RagInputError(ValueError):
    code = "chat_input_invalid"


@dataclass(frozen=True, slots=True)
class Citation:
    reference_id: str
    document_id: int
    chunk_id: int
    source_name: str
    start_char: int
    end_char: int
    excerpt: str
    page_number: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TutorResponse:
    status: Literal["answered", "insufficient_context"]
    answer: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class _ContextSource:
    tutor_source: TutorSource
    metadata: dict[str, Any]


class RagTutorService:
    def __init__(
        self,
        search_service: SearchService,
        chat_adapter: ChatAdapter,
        settings: Settings,
    ) -> None:
        self.search_service = search_service
        self.chat_adapter = chat_adapter
        self.settings = settings

    def answer(
        self,
        *,
        question: str,
        top_k: int,
        document_ids: Sequence[int] | None,
    ) -> TutorResponse:
        self._validate_input(question, top_k, document_ids)
        search = self.search_service.search(
            query=question,
            top_k=top_k,
            document_ids=document_ids,
        )
        if not search.results:
            return _insufficient_context()

        sources = self._build_context(search.results)
        if not sources:
            return _insufficient_context()
        model_output = self.chat_adapter.generate(
            question=question,
            sources=[source.tutor_source for source in sources],
        )
        return _assemble_response(model_output, sources)

    def _validate_input(
        self,
        question: str,
        top_k: int,
        document_ids: Sequence[int] | None,
    ) -> None:
        if len(question) > self.settings.chat_max_question_characters:
            raise RagInputError("Question exceeds the configured character limit")
        if top_k > self.settings.chat_max_top_k:
            raise RagInputError("top_k exceeds the configured chat limit")
        if document_ids is not None and len(document_ids) > self.settings.chat_max_document_ids:
            raise RagInputError("document_ids exceeds the configured chat limit")

    def _build_context(self, hits: Sequence[SearchHit]) -> tuple[_ContextSource, ...]:
        remaining = self.settings.chat_max_context_characters
        seen: set[tuple[int, int]] = set()
        sources: list[_ContextSource] = []
        for hit in hits:
            identity = (hit.document_id, hit.chunk_id)
            if identity in seen or remaining <= 0:
                continue
            seen.add(identity)
            take = min(
                len(hit.content),
                self.settings.chat_max_context_chunk_characters,
                remaining,
            )
            excerpt = hit.content[:take]
            if not excerpt.strip():
                continue
            reference_id = f"S{len(sources) + 1}"
            sources.append(
                _ContextSource(
                    tutor_source=TutorSource(
                        reference_id=reference_id,
                        document_id=hit.document_id,
                        chunk_id=hit.chunk_id,
                        source_name=hit.source_name,
                        start_char=hit.start_char,
                        end_char=hit.start_char + len(excerpt),
                        excerpt=excerpt,
                        page_number=hit.page_number,
                    ),
                    metadata=dict(hit.metadata),
                )
            )
            remaining -= len(excerpt)
        return tuple(sources)


def _assemble_response(
    output: ModelTutorOutput,
    sources: Sequence[_ContextSource],
) -> TutorResponse:
    if output.status == "insufficient_context":
        if any(section.reference_ids for section in output.sections):
            raise ChatOutputInvalidError(
                "Insufficient-context output must not cite retrieved chunks"
            )
        return _insufficient_context()

    if not output.sections:
        raise ChatOutputInvalidError("Answered output contains no answer sections")
    source_map = {source.tutor_source.reference_id: source for source in sources}
    used_ids: list[str] = []
    answer_parts: list[str] = []
    for section in output.sections:
        text = section.text.strip()
        if not text or len(text) > 4_000 or not section.reference_ids:
            raise ChatOutputInvalidError(
                "Every answered section must contain text and supporting references"
            )
        if _CITATION_MARKER.search(text):
            raise ChatOutputInvalidError("Model text must not contain citation markers")
        section_ids: list[str] = []
        for reference_id in section.reference_ids:
            if reference_id not in source_map:
                raise ChatOutputInvalidError("Model cited a source outside the supplied context")
            if reference_id not in section_ids:
                section_ids.append(reference_id)
            if reference_id not in used_ids:
                used_ids.append(reference_id)
        markers = " ".join(f"[{reference_id}]" for reference_id in section_ids)
        answer_parts.append(f"{text}\n{markers}")

    citations = tuple(_citation_from_context(source_map[reference_id]) for reference_id in used_ids)
    return TutorResponse(
        status="answered",
        answer="\n\n".join(answer_parts),
        citations=citations,
    )


def _citation_from_context(source: _ContextSource) -> Citation:
    value = source.tutor_source
    return Citation(
        reference_id=value.reference_id,
        document_id=value.document_id,
        chunk_id=value.chunk_id,
        source_name=value.source_name,
        start_char=value.start_char,
        end_char=value.end_char,
        excerpt=value.excerpt,
        page_number=value.page_number,
        metadata=source.metadata,
    )


def _insufficient_context() -> TutorResponse:
    return TutorResponse(
        status="insufficient_context",
        answer=INSUFFICIENT_CONTEXT_ANSWER,
        citations=(),
    )
