from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_returns_metadata(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["name"] == "Tributary"
    assert response.json()["docs"] == "/docs"


def test_health_checks_the_database(client: TestClient, settings) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "Tributary",
        "version": "0.1.0",
        "database": settings.database_label,
    }
    if settings.database_url.startswith("sqlite"):
        assert settings.db_path.exists()


def test_cors_preflight_does_not_allow_credentials(client: TestClient) -> None:
    response = client.options(
        "/api/items",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in response.headers
