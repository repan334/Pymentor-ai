import importlib
from pathlib import Path

import pytest
from app.core.config import Settings
from fastapi import FastAPI
from pydantic import ValidationError


def test_api_settings_do_not_require_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "APP_NAME",
        "APP_ENV",
        "APP_DEBUG",
        "API_V1_PREFIX",
        "DATABASE_URL",
        "DATABASE_URL_UNPOOLED",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_name == "PyMentor AI"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.database_url is None


def test_entrypoint_imports_without_dotenv_or_database_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)

    main_module = importlib.import_module("app.main")

    assert isinstance(main_module.app, FastAPI)


@pytest.mark.parametrize("prefix", ["api/v1", "/", "/api/v1/", "/api/v1?debug=true"])
def test_api_prefix_rejects_invalid_paths(prefix: str) -> None:
    with pytest.raises(ValidationError, match="API_V1_PREFIX"):
        Settings(_env_file=None, api_v1_prefix=prefix)


def test_ingestion_limits_have_safe_defaults() -> None:
    settings = Settings(_env_file=None, database_url=None)

    assert settings.max_upload_size_bytes == 10 * 1024 * 1024
    assert settings.max_multipart_body_size_bytes == 11 * 1024 * 1024
    assert settings.max_pdf_pages == 200
    assert settings.max_extracted_characters == 2_000_000
    assert settings.ingestion_chunk_overlap < settings.ingestion_chunk_size


def test_multipart_limit_must_leave_room_for_file_envelope() -> None:
    with pytest.raises(ValidationError, match="MAX_MULTIPART_BODY_SIZE_MB"):
        Settings(
            _env_file=None,
            max_upload_size_mb=10,
            max_multipart_body_size_mb=10,
        )


def test_chunk_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError, match="INGESTION_CHUNK_OVERLAP"):
        Settings(
            _env_file=None,
            ingestion_chunk_size=100,
            ingestion_chunk_overlap=100,
        )
