from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tributary.config import Settings
from tributary.db import create_engine, create_session_factory, init_db


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
    monkeypatch.setenv("TRIBUTARY_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("TRIBUTARY_SENTRY_DSN", raising=False)
    return Settings(_env_file=None)


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    engine = create_engine(settings)
    init_db(engine)
    try:
        yield engine
    finally:
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
def client(settings: Settings) -> Iterator[TestClient]:
    from tributary.main import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
