from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tributary.config import BACKEND_ROOT, Settings
from tributary.db import (
    BASELINE_REVISION,
    HEAD_REVISION,
    Base,
    create_engine,
    init_db,
)
from tributary.models import Label


def _alembic_config(connection) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def _stamp_baseline_only(engine) -> None:
    with engine.connect() as connection:
        command.upgrade(_alembic_config(connection), BASELINE_REVISION)


def _remove_alembic_version(engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE alembic_version")


def test_fresh_database_is_at_head(engine) -> None:
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert revision == HEAD_REVISION


def test_migrated_schema_contains_every_model_column(engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        assert table.name in table_names
        database_columns = {
            column["name"] for column in inspector.get_columns(table.name)
        }
        assert {column.name for column in table.columns} == database_columns


def test_legacy_sqlite_database_is_stamped_and_upgraded(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        _stamp_baseline_only(engine)
        assert "name_key" not in {
            column["name"] for column in inspect(engine).get_columns("labels")
        }
        _remove_alembic_version(engine)

        init_db(engine)

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            label_sql = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name = 'labels'")
            ).scalar_one()
        assert revision == HEAD_REVISION
        assert "name_key" in label_sql
    finally:
        engine.dispose()


def test_legacy_label_rows_are_backfilled_with_a_casefolded_key(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-labels.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        _stamp_baseline_only(engine)
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO labels (name) VALUES (:name)"),
                {"name": "Straße"},
            )
        _remove_alembic_version(engine)

        init_db(engine)

        with engine.connect() as connection:
            key = connection.execute(
                text("SELECT name_key FROM labels WHERE name = 'Straße'")
            ).scalar_one()
        assert key == "strasse"
    finally:
        engine.dispose()


def test_label_uniqueness_uses_name_key(db_session: Session) -> None:
    db_session.add(Label(name="Python"))
    db_session.commit()

    db_session.add(Label(name="python"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
