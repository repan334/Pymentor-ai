from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DatabaseSettings, get_database_settings


def create_database_engine(
    settings: DatabaseSettings | None = None,
    *,
    for_migrations: bool = False,
) -> Engine:
    selected_settings = settings or get_database_settings()
    url = selected_settings.migration_url if for_migrations else selected_settings.application_url
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=create_database_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


def get_session() -> Iterator[Session]:
    """Yield a transaction-scoped session suitable for dependency injection."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
