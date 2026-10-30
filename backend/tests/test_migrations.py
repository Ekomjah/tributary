from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from tributary.config import BACKEND_ROOT
from tributary.db import (
    BASELINE_REVISION,
    HEAD_REVISION,
    Base,
)


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
