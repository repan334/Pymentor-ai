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


def test_phase_5_embedding_profile_has_fixed_verified_identity() -> None:
    settings = Settings(_env_file=None, database_url=None, gemini_api_key=None)

    assert settings.embedding_provider == "gemini"
    assert settings.embedding_model == "gemini-embedding-2"
    assert settings.embedding_dimensions == 768
    assert settings.embedding_profile_key == (
        "gemini:gemini-embedding-2:768:retrieval-asymmetric-v1"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_provider", "other"),
        ("embedding_model", "another-model"),
        ("embedding_dimensions", 3072),
    ],
)
def test_incompatible_embedding_profile_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_phase_6_chat_profile_and_budgets_have_safe_defaults() -> None:
    settings = Settings(_env_file=None, database_url=None, gemini_api_key=None)

    assert settings.llm_provider == "gemini"
    assert settings.llm_model == "gemini-3.6-flash"
    assert settings.gemini_api_version == "v1beta"
    assert settings.llm_profile_key == "gemini:gemini-3.6-flash:grounded-tutor-v2"
    assert settings.chat_thinking_budget < settings.chat_max_output_tokens
    assert settings.chat_max_context_chunk_characters <= settings.chat_max_context_characters
    assert settings.chat_max_top_k <= 20
    assert settings.quiz_prompt_version == "grounded-quiz-v2"
    assert settings.quiz_max_question_count == 5
    assert settings.quiz_thinking_budget < settings.quiz_max_output_tokens
    assert settings.quiz_max_context_chunk_characters <= settings.quiz_max_context_characters
    assert settings.max_json_body_size_mb == 1
    assert settings.max_json_body_size_bytes == 1024 * 1024


@pytest.mark.parametrize(
    "overrides",
    [
        {"llm_provider": "other"},
        {"llm_model": "another-model"},
        {"llm_prompt_version": "unknown"},
        {"gemini_api_version": "v1"},
        {"chat_thinking_budget": 2048, "chat_max_output_tokens": 2048},
        {"chat_max_context_characters": 10, "chat_max_context_chunk_characters": 11},
        {"chat_max_top_k": 21},
        {"chat_max_question_characters": 0},
        {"chat_max_document_ids": 0},
        {"quiz_prompt_version": "unknown"},
        {"quiz_max_question_count": 6},
        {"quiz_retrieval_top_k": 21},
        {"quiz_max_context_characters": 10, "quiz_max_context_chunk_characters": 11},
        {"quiz_thinking_budget": 2048, "quiz_max_output_tokens": 2048},
        {"max_json_body_size_mb": 0},
    ],
)
def test_incompatible_chat_profiles_and_limits_are_rejected(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)
