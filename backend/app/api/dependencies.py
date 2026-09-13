from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_session
from app.documents.service import DocumentService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_document_service(
    session: Annotated[Session, Depends(get_session)],
) -> DocumentService:
    return DocumentService(session)
