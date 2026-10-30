from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tributary.config import ConfigurationError, Settings, get_settings

_ENV_KEYS = (
    "SENTRY_DSN",
    "TRIBUTARY_SENTRY_DSN",
    "SENTRY_ENABLED",
    "OLLAMA_MODEL",
    "TRIBUTARY_OLLAMA_MODEL",
    "OLLAMA_HOST",
    "TRIBUTARY_OLLAMA_HOST",
    "OLLAMA_CLOUD",
    "TRIBUTARY_OLLAMA_CLOUD",
    "OLLAMA_API_KEY",
    "TRIBUTARY_OLLAMA_API_KEY",
    "OLLAMA_CLOUD_MODEL",
    "TRIBUTARY_OLLAMA_CLOUD_MODEL",
    "OLLAMA_CLOUD_HOST",
    "TRIBUTARY_OLLAMA_CLOUD_HOST",
    "OLLAMA_TIMEOUT",
    "TRIBUTARY_OLLAMA_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_have_local_defaults(monkeypatch) -> None:
    monkeypatch.delenv("TRIBUTARY_DB_PATH", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("SENTRY_ENABLED", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_name == "Tributary"
    assert settings.ollama_model == "gemma3:1b"
    assert settings.sentry_enabled is True
    assert settings.sentry_traces_sample_rate > 0
    assert settings.fetch_timeout == 20.0
    assert settings.database_url.startswith("sqlite:///")
    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_sentry_is_only_active_when_a_dsn_is_configured() -> None:
    assert Settings(_env_file=None).sentry_active is False
    assert (
        Settings(
            _env_file=None,
            sentry_dsn="https://public@example.com/1",
        ).sentry_active
        is True
    )
    assert (
        Settings(
            _env_file=None,
            sentry_dsn="https://public@example.com/1",
            sentry_enabled=False,
        ).sentry_active
        is False
    )


def test_ollama_cloud_uses_cloud_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_CLOUD", "true")
    monkeypatch.setenv("OLLAMA_API_KEY", "cloud-key")

    settings = Settings(_env_file=None)

    assert settings.ollama_cloud is True
    assert settings.active_ollama_model == "gemma4:3b"
    assert settings.active_ollama_host == "https://ollama.com"
    assert settings.ollama_auth_headers == {
        "Authorization": "Bearer cloud-key"
    }


def test_ollama_cloud_accepts_explicit_cloud_overrides() -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud=True,
        ollama_api_key="cloud-key",
        ollama_cloud_model="gemma4:3b-cloud",
        ollama_cloud_host="https://gateway.example.com",
    )

    assert settings.active_ollama_model == "gemma4:3b-cloud"
    assert settings.active_ollama_host == "https://gateway.example.com"


def test_ollama_cloud_requires_an_api_key() -> None:
    with pytest.raises(ValidationError, match="OLLAMA_API_KEY"):
        Settings(_env_file=None, ollama_cloud=True)

    with pytest.raises(ValidationError, match="OLLAMA_API_KEY"):
        Settings(_env_file=None, ollama_cloud=True, ollama_api_key="   ")


def test_get_settings_reports_a_clear_cloud_key_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("OLLAMA_CLOUD", "true")
    monkeypatch.setenv("OLLAMA_API_KEY", "")

    try:
        with pytest.raises(ConfigurationError) as excinfo:
            get_settings()
    finally:
        get_settings.cache_clear()

    assert "OLLAMA_CLOUD=true requires OLLAMA_API_KEY" in str(excinfo.value)


def test_local_ollama_values_do_not_override_cloud_defaults() -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud=True,
        ollama_api_key="cloud-key",
        ollama_model="local:1b",
        ollama_host="http://local:11434",
    )

    assert settings.active_ollama_model == "gemma4:3b"
    assert settings.active_ollama_host == "https://ollama.com"


def test_db_path_can_be_overridden(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "custom.db"
    monkeypatch.setenv("TRIBUTARY_DB_PATH", str(target))
    settings = Settings(_env_file=None)

    assert settings.db_path == target.resolve()
    assert settings.database_url == f"sqlite:///{target.resolve().as_posix()}"
