from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tributary.config import Settings
from tributary.db import create_engine, create_session_factory, init_db
from tributary.main import create_app


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("TRIBUTARY_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
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
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
