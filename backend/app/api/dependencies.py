from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.chat.gemini import GeminiChatAdapter
from app.core.config import Settings
from app.db.session import get_session
from app.documents.service import DocumentService
from app.embeddings.gemini import GeminiEmbeddingAdapter
from app.progress.service import ProgressService
from app.quiz.service import QuizService
from app.rag.service import RagTutorService
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


def get_chat_adapter(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Iterator[GeminiChatAdapter]:
    adapter = GeminiChatAdapter(settings)
    try:
        yield adapter
    finally:
        adapter.close()


def get_rag_tutor_service(
    search_service: Annotated[SearchService, Depends(get_search_service)],
    chat_adapter: Annotated[GeminiChatAdapter, Depends(get_chat_adapter)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> RagTutorService:
    return RagTutorService(search_service, chat_adapter, settings)


def get_quiz_service(
    session: Annotated[Session, Depends(get_session)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    chat_adapter: Annotated[GeminiChatAdapter, Depends(get_chat_adapter)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> QuizService:
    return QuizService(session, search_service, chat_adapter, settings)


def get_progress_service(
    session: Annotated[Session, Depends(get_session)],
) -> ProgressService:
    return ProgressService(session)
