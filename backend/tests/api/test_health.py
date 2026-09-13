import pytest
from app.core.config import Settings
from app.factory import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_name="PyMentor AI Test",
        app_env="test",
        app_debug=False,
        api_v1_prefix="/api/v1",
        database_url=None,
        database_url_unpooled=None,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health_returns_process_status_without_database_credentials(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_router_uses_configured_api_prefix() -> None:
    settings = Settings(
        _env_file=None,
        api_v1_prefix="/custom/v1",
        database_url=None,
    )
    client = TestClient(create_app(settings))

    assert client.get("/custom/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 404


def test_health_is_registered_in_openapi_without_configuration_secrets(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/health" in schema["paths"]
    assert "get" in schema["paths"]["/api/v1/health"]
    assert "database_url" not in response.text.lower()
    assert "password" not in response.text.lower()


def test_development_docs_are_available(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_unknown_route_keeps_standard_not_found_response(client: TestClient) -> None:
    response = client.get("/api/v1/unknown")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_unsupported_method_keeps_standard_method_response(client: TestClient) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}
