from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import DateTime, MetaData, event, inspect, select
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import BACKEND_ROOT, Settings

if TYPE_CHECKING:
    from .models import User

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

BASELINE_REVISION = "0001_baseline"
USERS_REVISION = "0003_users"
HEAD_REVISION = "0004_ownership"
# Internal foreign-key anchor for account-free local installs. It is not an
# account and is never accepted in cloud mode.
LOCAL_AUTH0_SUB = "local"
# Tables that existed at the baseline revision. A pre-Alembic SQLite file may
# be missing one of these; create_all fills the gap. Tables introduced by later
# revisions must be created by their migration, not by create_all.
_BASELINE_TABLES = frozenset(
    {
        "box_cache",
        "feeds",
        "item_labels",
        "items",
        "labels",
        "pipe_feed_items",
        "pipes",
        "runs",
        "search_cache",
    }
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator):
    """Store naive UTC and return timezone-aware UTC values on every dialect."""

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


def create_engine(settings: Settings, *, database_url: str | None = None) -> Engine:
    """Build an engine for SQLite (local) or PostgreSQL (cloud).

    ``database_url`` lets the caller open a second engine, for example the
    direct Neon host used for migrations while the application keeps using the
    pooled one.
    """

    url_text = database_url or settings.database_url
    url = make_url(url_text)
    backend = url.get_backend_name()

    if backend == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)

        engine = sa_create_engine(
            url_text,
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

    if backend == "postgresql":
        # Neon suspends idle computes and closes idle server connections, so a
        # pooled connection can go stale between requests. pre_ping tests it
        # before use and recycle bounds its lifetime; both recover the pool
        # without surfacing an error to the request.
        return sa_create_engine(
            url_text,
            connect_args={
                "connect_timeout": settings.database_connect_timeout,
                "application_name": "tributary",
            },
            pool_pre_ping=True,
            pool_recycle=settings.database_pool_recycle,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
        )

    raise RuntimeError(f"Unsupported database backend: {backend!r}")


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


def _legacy_migrate_feeds(engine: Engine) -> None:
    """Add feed columns that predate Alembic to an existing SQLite database."""

    with engine.begin() as connection:
        existing = {str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(feeds)")}
        for name, ddl in _FEED_COLUMNS.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE feeds ADD COLUMN {name} {ddl}")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_feeds_pipe_id ON feeds(pipe_id)"
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_feeds_kind ON feeds(kind)")


def _legacy_migrate_runs(engine: Engine) -> None:
    """Add run snapshots that predate Alembic to an existing SQLite database."""

    with engine.begin() as connection:
        existing = {str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
        for name, ddl in _RUN_COLUMNS.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")


def _legacy_migrate_items(engine: Engine) -> None:
    """Add reader columns that predate Alembic to an existing SQLite database."""

    with engine.begin() as connection:
        existing = {str(row[1]) for row in connection.exec_driver_sql("PRAGMA table_info(items)")}
        for name, ddl in _ITEM_COLUMNS.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE items ADD COLUMN {name} {ddl}")


def _alembic_config(connection: Any) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    # Startup migrations should not write INFO lines into CLI output.
    config.attributes["configure_logger"] = False
    return config


def _upgrade_to_head(engine: Engine) -> None:
    with engine.connect() as connection:
        command.upgrade(_alembic_config(connection), "head")


def _stamp(engine: Engine, revision: str) -> None:
    with engine.connect() as connection:
        command.stamp(_alembic_config(connection), revision)


def _legacy_sqlite_tables(engine: Engine, tables: set[str]) -> None:
    """Bring a pre-Alembic SQLite file to the baseline, then upgrade it."""

    if "feeds" in tables:
        _legacy_migrate_feeds(engine)
    if "items" in tables:
        _legacy_migrate_items(engine)
    if "runs" in tables:
        _legacy_migrate_runs(engine)

    from . import models  # noqa: F401  (registers metadata)

    if "labels" not in tables:
        # This file predates the label table. create_all builds missing tables
        # in their latest shape, so stamp the users revision and let the
        # ownership migration add owner_id to tables that already existed.
        missing = [
            table
            for table in Base.metadata.sorted_tables
            if table.name not in tables
        ]
        if missing:
            Base.metadata.create_all(engine, tables=missing)
        _stamp(engine, USERS_REVISION)
        _upgrade_to_head(engine)
        return

    # The file already contains the baseline label table, so 0002 must still
    # run. Only fill in missing baseline tables; later revisions (users) are
    # created by their own migrations.
    missing = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in tables and table.name in _BASELINE_TABLES
    ]
    if missing:
        Base.metadata.create_all(engine, tables=missing)

    _stamp(engine, BASELINE_REVISION)
    _upgrade_to_head(engine)


def ensure_local_user(db: Session) -> User:
    """Return the single account-free user used by local installations."""

    from .models import User

    user = db.scalar(select(User).where(User.auth0_sub == LOCAL_AUTH0_SUB))
    if user is not None:
        return user

    user = User(
        auth0_sub=LOCAL_AUTH0_SUB,
        name="Local",
        last_seen_at=utcnow(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Another process created the anchor first; use the existing row.
        db.rollback()
        user = db.scalar(select(User).where(User.auth0_sub == LOCAL_AUTH0_SUB))
        if user is None:  # pragma: no cover - defensive
            raise
    else:
        db.refresh(user)
    return user


def _ensure_local_anchor(engine: Engine) -> None:
    with Session(engine) as session:
        ensure_local_user(session)


def init_db(engine: Engine, settings: Settings | None = None) -> None:
    """Create or upgrade the schema.

    When ``MIGRATION_DATABASE_URL`` points somewhere else (the direct Neon host),
    DDL runs on a short-lived engine there while the application keeps its
    pooled connection.

    Local installations also get their internal user here, so the reader can
    start with an empty database and no sign-in step. Cloud mode never creates
    the local anchor.
    """

    if settings is not None and settings.migration_database_url:
        if settings.migration_url != settings.database_url:
            migration_engine = create_engine(
                settings,
                database_url=settings.migration_url,
            )
            try:
                _init_db(migration_engine)
            finally:
                migration_engine.dispose()
            if settings.is_cloud:
                return
            _ensure_local_anchor(engine)
            return

    _init_db(engine)
    if settings is None or not settings.is_cloud:
        _ensure_local_anchor(engine)


def _init_db(engine: Engine) -> None:
    from . import models  # noqa: F401  (registers metadata)

    tables = set(inspect(engine).get_table_names())
    if not tables or "alembic_version" in tables:
        _upgrade_to_head(engine)
        return

    if engine.dialect.name != "sqlite":
        raise RuntimeError(
            "The database has tables but no Alembic revision. "
            "Stamp the baseline before starting Tributary."
        )

    _legacy_sqlite_tables(engine, tables)


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
