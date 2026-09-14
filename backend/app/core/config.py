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

    embedding_provider: str = "gemini"
    embedding_model: str = "gemini-embedding-2"
    embedding_dimensions: int = 768
    embedding_input_version: str = "retrieval-asymmetric-v1"
    gemini_api_version: str = "v1beta"
    gemini_api_key: SecretStr | None = None
    embedding_request_timeout_seconds: int = 30
    embedding_max_attempts: int = 3
    embedding_retry_base_seconds: float = 0.5
    embedding_batch_size: int = 16
    max_index_chunks: int = 200
    max_indexing_seconds: int = 120
    index_claim_timeout_seconds: int = 300
    max_search_query_characters: int = 2_000
    max_search_document_ids: int = 100

    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.6-flash"
    llm_prompt_version: str = "grounded-tutor-v2"
    chat_request_timeout_seconds: int = 45
    chat_max_attempts: int = 2
    chat_retry_base_seconds: float = 0.5
    chat_max_question_characters: int = 2_000
    chat_max_document_ids: int = 100
    chat_max_top_k: int = 8
    chat_max_context_characters: int = 12_000
    chat_max_context_chunk_characters: int = 4_000
    chat_max_output_tokens: int = 2_048
    chat_thinking_budget: int = 512
    chat_temperature: float = 0.2

    database_url: SecretStr | None = None
    database_url_unpooled: SecretStr | None = None
    neon_branch: str | None = None

    @field_validator(
        "app_name",
        "app_env",
        "embedding_provider",
        "embedding_model",
        "embedding_input_version",
        "gemini_api_version",
        "llm_provider",
        "llm_model",
        "llm_prompt_version",
    )
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
        "embedding_dimensions",
        "embedding_request_timeout_seconds",
        "embedding_max_attempts",
        "embedding_batch_size",
        "max_index_chunks",
        "max_indexing_seconds",
        "index_claim_timeout_seconds",
        "max_search_query_characters",
        "max_search_document_ids",
        "chat_request_timeout_seconds",
        "chat_max_attempts",
        "chat_max_question_characters",
        "chat_max_document_ids",
        "chat_max_top_k",
        "chat_max_context_characters",
        "chat_max_context_chunk_characters",
        "chat_max_output_tokens",
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

    @field_validator("embedding_retry_base_seconds", "chat_retry_base_seconds")
    @classmethod
    def validate_retry_delay(cls, value: float) -> float:
        if value < 0:
            raise ValueError("must be non-negative")
        return value

    @field_validator("chat_thinking_budget")
    @classmethod
    def validate_thinking_budget(cls, value: int) -> int:
        if value < 0:
            raise ValueError("CHAT_THINKING_BUDGET must be non-negative")
        return value

    @field_validator("chat_temperature")
    @classmethod
    def validate_chat_temperature(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("CHAT_TEMPERATURE must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_ingestion_limits(self) -> "Settings":
        if self.max_multipart_body_size_mb <= self.max_upload_size_mb:
            raise ValueError("MAX_MULTIPART_BODY_SIZE_MB must be greater than MAX_UPLOAD_SIZE_MB")
        if self.ingestion_chunk_overlap >= self.ingestion_chunk_size:
            raise ValueError("INGESTION_CHUNK_OVERLAP must be smaller than INGESTION_CHUNK_SIZE")
        if self.embedding_provider != "gemini":
            raise ValueError("EMBEDDING_PROVIDER must be 'gemini' in the Phase 5 profile")
        if self.embedding_model != "gemini-embedding-2":
            raise ValueError("EMBEDDING_MODEL must be 'gemini-embedding-2' in the Phase 5 profile")
        if self.embedding_dimensions != 768:
            raise ValueError("EMBEDDING_DIMENSIONS must be 768 for the database vector schema")
        if self.gemini_api_version != "v1beta":
            raise ValueError("GEMINI_API_VERSION must be 'v1beta' for the configured Developer API")
        if self.llm_provider != "gemini":
            raise ValueError("LLM_PROVIDER must be 'gemini' in the Phase 6 profile")
        if self.llm_model != "gemini-3.6-flash":
            raise ValueError("LLM_MODEL must be 'gemini-3.6-flash' in the active chat profile")
        if self.llm_prompt_version != "grounded-tutor-v2":
            raise ValueError("LLM_PROMPT_VERSION must be 'grounded-tutor-v2'")
        if self.chat_max_context_chunk_characters > self.chat_max_context_characters:
            raise ValueError(
                "CHAT_MAX_CONTEXT_CHUNK_CHARACTERS must not exceed CHAT_MAX_CONTEXT_CHARACTERS"
            )
        if self.chat_thinking_budget >= self.chat_max_output_tokens:
            raise ValueError("CHAT_THINKING_BUDGET must be smaller than CHAT_MAX_OUTPUT_TOKENS")
        if self.chat_max_top_k > 20:
            raise ValueError("CHAT_MAX_TOP_K must not exceed the search contract maximum of 20")
        return self

    @property
    def embedding_profile_key(self) -> str:
        return ":".join(
            (
                self.embedding_provider,
                self.embedding_model,
                str(self.embedding_dimensions),
                self.embedding_input_version,
            )
        )

    @property
    def gemini_key_value(self) -> str:
        value = _read_secret(self.gemini_api_key, name="GEMINI_API_KEY")
        if value is None:
            raise ValueError("GEMINI_API_KEY is required for Gemini operations")
        return value

    @property
    def llm_profile_key(self) -> str:
        return ":".join((self.llm_provider, self.llm_model, self.llm_prompt_version))

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
