from functools import lru_cache

from pydantic import SecretStr, field_validator, model_validator
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


class Settings(BaseSettings):
    """Application settings loaded from environment, .env, or .env.local."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PyMentor AI"
    app_env: str = "development"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"

    max_upload_size_mb: int = 10
    max_multipart_body_size_mb: int = 11
    max_pdf_pages: int = 200
    max_extracted_characters: int = 2_000_000
    ingestion_chunk_size: int = 500
    ingestion_chunk_overlap: int = 100

    database_url: SecretStr | None = None
    database_url_unpooled: SecretStr | None = None
    neon_branch: str | None = None

    @field_validator("app_name", "app_env")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_v1_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            raise ValueError("API_V1_PREFIX must start with '/'")
        if value == "/" or value.endswith("/"):
            raise ValueError("API_V1_PREFIX must not be '/' or end with '/'")
        if "?" in value or "#" in value:
            raise ValueError("API_V1_PREFIX must be a path without query or fragment")
        return value

    @field_validator(
        "max_upload_size_mb",
        "max_multipart_body_size_mb",
        "max_pdf_pages",
        "max_extracted_characters",
        "ingestion_chunk_size",
    )
    @classmethod
    def validate_positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("ingestion_chunk_overlap")
    @classmethod
    def validate_non_negative_overlap(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_ingestion_limits(self) -> "Settings":
        if self.max_multipart_body_size_mb <= self.max_upload_size_mb:
            raise ValueError("MAX_MULTIPART_BODY_SIZE_MB must be greater than MAX_UPLOAD_SIZE_MB")
        if self.ingestion_chunk_overlap >= self.ingestion_chunk_size:
            raise ValueError("INGESTION_CHUNK_OVERLAP must be smaller than INGESTION_CHUNK_SIZE")
        return self

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def max_multipart_body_size_bytes(self) -> int:
        return self.max_multipart_body_size_mb * 1024 * 1024

    @property
    def application_url(self) -> URL:
        value = _read_secret(self.database_url, name="DATABASE_URL")
        if value is None:
            raise ValueError("DATABASE_URL is required for database operations")
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
def get_settings() -> Settings:
    return Settings()


# Compatibility names keep the existing Phase 3 imports on the same settings system.
DatabaseSettings = Settings
get_database_settings = get_settings
