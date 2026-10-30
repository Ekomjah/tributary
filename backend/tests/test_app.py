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
