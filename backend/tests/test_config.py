from __future__ import annotations

from pathlib import Path

from tributary.config import Settings


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


def test_db_path_can_be_overridden(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "custom.db"
    monkeypatch.setenv("TRIBUTARY_DB_PATH", str(target))
    settings = Settings(_env_file=None)

    assert settings.db_path == target.resolve()
    assert settings.database_url == f"sqlite:///{target.resolve().as_posix()}"
