from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tributary.config import (
    DEFAULT_CORS_ORIGINS,
    ConfigurationError,
    Settings,
    get_settings,
)

_ENV_KEYS = (
    "DEV_ENV",
    "TRIBUTARY_DEV_ENV",
    "TRIBUTARY_DB_PATH",
    "DB_PATH",
    "DATABASE_URL",
    "TRIBUTARY_DATABASE_URL",
    "DATABASE",
    "TRIBUTARY_DATABASE",
    "MIGRATION_DATABASE_URL",
    "TRIBUTARY_MIGRATION_DATABASE_URL",
    "DATABASE_POOL_SIZE",
    "TRIBUTARY_DATABASE_POOL_SIZE",
    "DATABASE_MAX_OVERFLOW",
    "TRIBUTARY_DATABASE_MAX_OVERFLOW",
    "DATABASE_POOL_TIMEOUT",
    "TRIBUTARY_DATABASE_POOL_TIMEOUT",
    "DATABASE_POOL_RECYCLE",
    "TRIBUTARY_DATABASE_POOL_RECYCLE",
    "DATABASE_CONNECT_TIMEOUT",
    "TRIBUTARY_DATABASE_CONNECT_TIMEOUT",
    "AUTH0_DOMAIN",
    "TRIBUTARY_AUTH0_DOMAIN",
    "AUTH0_AUDIENCE",
    "TRIBUTARY_AUTH0_AUDIENCE",
    "AUTH0_CLIENT_ID",
    "TRIBUTARY_AUTH0_CLIENT_ID",
    "AUTH0_ALLOWED_SUBS",
    "TRIBUTARY_AUTH0_ALLOWED_SUBS",
    "CORS_ORIGINS",
    "TRIBUTARY_CORS_ORIGINS",
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


def _cloud_settings(**overrides) -> Settings:
    values = {
        "dev_env": "production",
        "database_url_override": "postgresql://user:pass@db.example.com:5432/tributary",
        "auth0_domain": "example.auth0.com",
        "auth0_audience": "https://api.example.com",
        "auth0_client_id": "spa-client-id",
        "cors_origins": "https://app.example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_settings_have_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "Tributary"
    assert settings.is_cloud is False
    assert settings.ollama_model == "gemma3:1b"
    assert settings.sentry_enabled is True
    assert settings.sentry_traces_sample_rate > 0
    assert settings.fetch_timeout == 20.0
    assert settings.database_url.startswith("sqlite:///")
    assert settings.allowed_cors_origins == DEFAULT_CORS_ORIGINS
    assert settings.auth0_issuer is None


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


def test_empty_dev_env_stays_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_ENV", "  ")
    settings = Settings(_env_file=None)

    assert settings.dev_env == ""
    assert settings.is_cloud is False


def test_database_url_can_be_used_without_cloud_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@db.example.com:5432/tributary",
    )
    settings = Settings(_env_file=None)

    assert settings.is_cloud is False
    assert settings.database_url == (
        "postgresql+psycopg://user:pass@db.example.com:5432/tributary"
    )
    assert settings.database_label == (
        "postgresql+psycopg://user:***@db.example.com:5432/tributary"
    )
    assert settings.database_backend == "postgresql"


def test_database_selector_defaults_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)

    assert settings.database == ""
    assert settings.database_backend == "sqlite"
    assert settings.migration_url == settings.database_url


def test_database_selector_accepts_postgres_with_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE", "postgres")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@db.example.com:5432/tributary",
    )

    settings = Settings(_env_file=None)

    assert settings.database == "postgres"
    assert settings.database_backend == "postgresql"


def test_database_postgres_requires_a_url() -> None:
    with pytest.raises(ValidationError, match="DATABASE=postgres requires DATABASE_URL"):
        Settings(_env_file=None, database="postgres")


def test_database_selector_rejects_a_conflicting_url() -> None:
    with pytest.raises(ValidationError, match="conflicts with the DATABASE_URL"):
        Settings(
            _env_file=None,
            database="postgres",
            database_url_override="sqlite:///local.db",
        )

    with pytest.raises(ValidationError, match="conflicts with the DATABASE_URL"):
        Settings(
            _env_file=None,
            database="sqlite",
            database_url_override="postgresql://u:p@host/db",
        )


def test_database_selector_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError, match="DATABASE must be"):
        Settings(_env_file=None, database="mysql")


def test_migration_database_url_uses_the_direct_host() -> None:
    settings = _cloud_settings(
        database_url_override=(
            "postgresql://user:pass@"
            "ep-example-pooler.eu-central-1.aws.neon.tech/tributary"
        ),
        migration_database_url=(
            "postgres://user:pass@ep-example.eu-central-1.aws.neon.tech/tributary"
        ),
    )

    assert settings.migration_database_url == (
        "postgres://user:pass@ep-example.eu-central-1.aws.neon.tech/tributary"
    )
    assert settings.migration_url == (
        "postgresql+psycopg://user:pass@"
        "ep-example.eu-central-1.aws.neon.tech/tributary"
    )
    # The application still uses the pooled URL.
    assert "pooler" in settings.database_url


def test_migration_database_url_must_be_postgres() -> None:
    with pytest.raises(ValidationError, match="MIGRATION_DATABASE_URL must be"):
        Settings(_env_file=None, migration_database_url="sqlite:///local.db")


def test_postgres_pool_defaults_are_conservative() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_pool_size == 5
    assert settings.database_max_overflow == 5
    assert settings.database_pool_timeout == 30.0
    assert settings.database_pool_recycle == 300
    assert settings.database_connect_timeout == 10


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgres://u:p@host:5432/db",
            "postgresql+psycopg://u:p@host:5432/db",
        ),
        (
            "postgresql://u:p@host:5432/db",
            "postgresql+psycopg://u:p@host:5432/db",
        ),
        (
            "postgresql+psycopg2://u:p@host:5432/db",
            "postgresql+psycopg://u:p@host:5432/db",
        ),
        (
            "postgresql+psycopg://u:p@host:5432/db",
            "postgresql+psycopg://u:p@host:5432/db",
        ),
    ],
)
def test_postgres_urls_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", raw)
    settings = Settings(_env_file=None)

    assert settings.database_url == expected


def test_database_url_rejects_unsupported_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pass@host/db")

    with pytest.raises(ValidationError, match="SQLite or PostgreSQL"):
        Settings(_env_file=None)


def test_cloud_mode_requires_postgres_and_auth_zero() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            _env_file=None,
            dev_env="production",
            auth0_domain="example.auth0.com",
            auth0_audience="https://api.example.com",
            auth0_client_id="spa-client-id",
            cors_origins="https://app.example.com",
        )

    with pytest.raises(ValidationError, match="AUTH0_DOMAIN"):
        Settings(
            _env_file=None,
            dev_env="production",
            database_url_override="postgresql://u:p@host/db",
            auth0_audience="https://api.example.com",
            auth0_client_id="spa-client-id",
            cors_origins="https://app.example.com",
        )

    with pytest.raises(ValidationError, match="PostgreSQL DATABASE_URL"):
        _cloud_settings(database_url_override="sqlite:///local.db")


def test_cloud_mode_requires_explicit_cors_origins() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        _cloud_settings(cors_origins=None)


def test_cloud_mode_accepts_a_complete_configuration() -> None:
    settings = _cloud_settings(
        auth0_domain="https://example.auth0.com/",
        auth0_allowed_subs="auth0|one, auth0|two, auth0|one",
    )

    assert settings.is_cloud is True
    assert settings.auth0_domain == "example.auth0.com"
    assert settings.auth0_issuer == "https://example.auth0.com/"
    assert settings.auth0_jwks_url == (
        "https://example.auth0.com/.well-known/jwks.json"
    )
    assert settings.allowed_cors_origins == ["https://app.example.com"]
    assert settings.auth0_allowed_subs == ["auth0|one", "auth0|two"]


def test_cors_origins_accept_comma_separated_and_json_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://app.example.com/, https://preview.example.com",
    )
    settings = Settings(_env_file=None)
    assert settings.allowed_cors_origins == [
        "https://app.example.com",
        "https://preview.example.com",
    ]

    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["https://one.example.com", "https://two.example.com"]',
    )
    settings = Settings(_env_file=None)
    assert settings.allowed_cors_origins == [
        "https://one.example.com",
        "https://two.example.com",
    ]


def test_cors_origins_reject_wildcards() -> None:
    with pytest.raises(ValidationError, match="explicit origins"):
        Settings(_env_file=None, cors_origins="*")
