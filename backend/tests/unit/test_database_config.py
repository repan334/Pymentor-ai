import pytest
from app.core.config import DatabaseSettings
from pydantic import SecretStr


def build_settings(
    application_url: str,
    migration_url: str | None = None,
) -> DatabaseSettings:
    return DatabaseSettings(
        database_url=SecretStr(application_url),
        database_url_unpooled=(SecretStr(migration_url) if migration_url is not None else None),
    )


def test_application_url_selects_psycopg_and_preserves_security_parameters() -> None:
    settings = build_settings(
        "postgresql://user:password@example-pooler.test/neondb"
        "?sslmode=require&channel_binding=require"
    )

    url = settings.application_url

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "example-pooler.test"
    assert url.query == {"sslmode": "require", "channel_binding": "require"}
    assert url.render_as_string(hide_password=True).find("password") == -1


def test_migration_url_prefers_direct_connection() -> None:
    settings = build_settings(
        "postgresql://user:password@example-pooler.test/neondb?sslmode=require",
        "postgresql://user:password@example.test/neondb?sslmode=require",
    )

    assert settings.migration_url.host == "example.test"


def test_migration_url_rejects_pooled_fallback() -> None:
    settings = build_settings(
        "postgresql://user:password@example-pooler.test/neondb?sslmode=require"
    )

    with pytest.raises(ValueError, match="DATABASE_URL_UNPOOLED is required"):
        _ = settings.migration_url


def test_migration_url_accepts_direct_application_url_as_fallback() -> None:
    settings = build_settings("postgresql://user:password@example.test/neondb?sslmode=require")

    assert settings.migration_url.host == "example.test"


def test_settings_repr_does_not_reveal_credentials() -> None:
    settings = build_settings("postgresql://user:highly-secret@example.test/neondb?sslmode=require")

    assert "highly-secret" not in repr(settings)
