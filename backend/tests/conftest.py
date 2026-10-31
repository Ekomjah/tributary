from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tributary import models  # noqa: F401  (registers Base.metadata)
from tributary.config import Settings
from tributary.db import (
    Base,
    create_engine,
    create_session_factory,
    init_db,
)

_MODE_ENV_KEYS = (
    "DEV_ENV",
    "TRIBUTARY_DEV_ENV",
    "DATABASE_URL",
    "TRIBUTARY_DATABASE_URL",
    "DATABASE_URL_UNPOOLED",
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
    "AUTH0_ALLOWED_EMAILS",
    "TRIBUTARY_AUTH0_ALLOWED_EMAILS",
    "CORS_ORIGINS",
    "TRIBUTARY_CORS_ORIGINS",
    "CORS_ORIGIN_REGEX",
    "TRIBUTARY_CORS_ORIGIN_REGEX",
)


def _reset_non_sqlite_database(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")


@pytest.fixture(autouse=True)
def _disable_sentry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never send telemetry from tests, even when a local .env has a DSN."""
    monkeypatch.setenv("SENTRY_ENABLED", "false")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("TRIBUTARY_SENTRY_DSN", raising=False)


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep URL validation offline; a test can override the resolver itself."""
    from tributary.services import urls

    monkeypatch.setattr(urls, "_resolve_host", lambda host, port: ["93.184.216.34"])


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key in _MODE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    test_database_url = os.environ.get("TRIBUTARY_TEST_DATABASE_URL")
    if test_database_url:
        monkeypatch.setenv("DATABASE_URL", test_database_url)
        monkeypatch.delenv("TRIBUTARY_DB_PATH", raising=False)
        monkeypatch.delenv("DB_PATH", raising=False)
    else:
        monkeypatch.setenv("TRIBUTARY_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.delenv("DB_PATH", raising=False)

    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("TRIBUTARY_SENTRY_DSN", raising=False)
    return Settings(_env_file=None)


@pytest.fixture
def database_backend(settings: Settings) -> str:
    return "postgresql" if settings.database_url.startswith("postgresql") else "sqlite"


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    engine = create_engine(settings)
    if engine.dialect.name != "sqlite":
        _reset_non_sqlite_database(engine)
    init_db(engine)
    try:
        yield engine
    finally:
        if engine.dialect.name != "sqlite":
            _reset_non_sqlite_database(engine)
        engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    """Start the app against an isolated schema.

    ``engine`` is requested so the shared PostgreSQL database is reset around
    each test, mirroring the fresh SQLite file each test gets locally.
    """
    from tributary.main import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def postgres_database_url() -> str:
    """Return the PostgreSQL test URL, skipping cloud tests on SQLite runs."""

    url = os.environ.get("TRIBUTARY_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("cloud mode requires a PostgreSQL test database")
    return url


@pytest.fixture
def cloud_settings(postgres_database_url: str) -> Settings:
    """Settings for a cloud-mode app backed by the PostgreSQL test database."""

    return Settings(
        _env_file=None,
        dev_env="test",
        database_url_override=postgres_database_url,
        auth0_domain="tenant.example",
        auth0_audience="https://api.example.test",
        auth0_client_id="spa-client-id",
        cors_origins="http://localhost:3000",
    )


@pytest.fixture
def cloud_client(cloud_settings: Settings) -> Iterator[TestClient]:
    """Start a cloud-mode app against the isolated PostgreSQL database."""

    from tributary.main import create_app

    reset_engine = create_engine(cloud_settings)
    _reset_non_sqlite_database(reset_engine)
    reset_engine.dispose()

    app = create_app(cloud_settings)
    with TestClient(app) as test_client:
        yield test_client

    reset_engine = create_engine(cloud_settings)
    _reset_non_sqlite_database(reset_engine)
    reset_engine.dispose()
