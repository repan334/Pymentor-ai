from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_session
from app.documents.service import DocumentService
from app.embeddings.gemini import GeminiEmbeddingAdapter
from app.retrieval.service import IndexingService, SearchService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_document_service(
    session: Annotated[Session, Depends(get_session)],
) -> DocumentService:
    return DocumentService(session)


def get_embedding_adapter(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Iterator[GeminiEmbeddingAdapter]:
    adapter = GeminiEmbeddingAdapter(settings)
    try:
        yield adapter
    finally:
        adapter.close()


def get_indexing_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    adapter: Annotated[GeminiEmbeddingAdapter, Depends(get_embedding_adapter)],
) -> IndexingService:
    return IndexingService(session, adapter, settings)


def get_search_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    adapter: Annotated[GeminiEmbeddingAdapter, Depends(get_embedding_adapter)],
) -> SearchService:
    return SearchService(session, adapter, settings)
