from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import DateTime, MetaData, event
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import Settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator):
    """Store naive UTC in SQLite and return timezone-aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError("UTCDateTime values must be datetime instances")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_engine(settings: Settings) -> Engine:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa_create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


_ITEM_COLUMNS: dict[str, str] = {
    "content_html": "TEXT",
    "author": "VARCHAR(200)",
    "cover_image": "TEXT",
    "cover_image_alt": "TEXT",
    "cover_caption": "TEXT",
    "content_full": "TEXT",
    "content_fetched_at": "DATETIME",
    "fetch_status": "VARCHAR(16)",
    "source": "VARCHAR(500)",
    "summary": "TEXT",
    "why_care": "TEXT",
}

_FEED_COLUMNS: dict[str, str] = {
    "kind": "VARCHAR(16) NOT NULL DEFAULT 'feed'",
    "pipe_id": "INTEGER",
}

_RUN_COLUMNS: dict[str, str] = {
    "steps_json": "TEXT NOT NULL DEFAULT '[]'",
    "item_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "error_step": "INTEGER",
    "error_box": "VARCHAR(50)",
}


def _migrate_feeds(engine: Engine) -> None:
    """Add the feed kind to an existing SQLite database."""

    with engine.begin() as connection:
        existing = {str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(feeds)")}
        for name, ddl in _FEED_COLUMNS.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE feeds ADD COLUMN {name} {ddl}")
        # ``create_all`` cannot add a unique constraint to an existing table.
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_feeds_pipe_id ON feeds(pipe_id)"
        )


def _migrate_runs(engine: Engine) -> None:
    """Add run snapshots to an existing SQLite database."""

    with engine.begin() as connection:
        existing = {str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
        for name, ddl in _RUN_COLUMNS.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")


def _migrate_items(engine: Engine) -> None:
    """Add reader columns to an existing SQLite database.

    ``create_all`` only creates missing tables, so a database made before the
    article extractor existed needs the new item columns added in place.
    """

    with engine.begin() as connection:
        existing = {str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(items)")}
        for name, ddl in _ITEM_COLUMNS.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE items ADD COLUMN {name} {ddl}")


def init_db(engine: Engine) -> None:
    # Importing the models registers their tables on Base.metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    _migrate_feeds(engine)
    _migrate_items(engine)
    _migrate_runs(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db(request: Request) -> Iterator[Session]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        yield session
