from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


def _read_secret(secret: SecretStr | None, *, name: str) -> str | None:
    if secret is None:
        return None

    value = secret.get_secret_value().strip()
    if not value:
        if name == "DATABASE_URL_UNPOOLED":
            return None
        raise ValueError(f"{name} must not be empty")
    return value


def _as_psycopg_url(value: str, *, name: str) -> URL:
    """Select Psycopg 3 explicitly without rebuilding or dropping URL parameters."""
    try:
        url = make_url(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a valid SQLAlchemy database URL") from exc

    if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError(f"{name} must be a PostgreSQL URL")

    return url.set(drivername="postgresql+psycopg")


def _is_pooled(url: URL) -> bool:
    return bool(url.host and "-pooler." in url.host.lower())


class DatabaseSettings(BaseSettings):
    """Database settings loaded from process environment, .env, or .env.local."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: SecretStr
    database_url_unpooled: SecretStr | None = None
    neon_branch: str | None = None

    @property
    def application_url(self) -> URL:
        value = _read_secret(self.database_url, name="DATABASE_URL")
        if value is None:  # pragma: no cover - DATABASE_URL is required above
            raise ValueError("DATABASE_URL must not be empty")
        return _as_psycopg_url(value, name="DATABASE_URL")

    @property
    def migration_url(self) -> URL:
        direct_value = _read_secret(
            self.database_url_unpooled,
            name="DATABASE_URL_UNPOOLED",
        )
        if direct_value is not None:
            url = _as_psycopg_url(direct_value, name="DATABASE_URL_UNPOOLED")
            if _is_pooled(url):
                raise ValueError("DATABASE_URL_UNPOOLED must use a direct Neon endpoint")
            return url

        url = self.application_url
        if _is_pooled(url):
            raise ValueError(
                "DATABASE_URL_UNPOOLED is required when DATABASE_URL uses a pooled endpoint"
            )
        return url


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()  # type: ignore[call-arg]
