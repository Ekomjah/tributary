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
    ensure_local_user,
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
    db_session.add(Label(owner_id=ensure_local_user(db_session).id, name="Python"))
    db_session.commit()

    db_session.add(Label(owner_id=ensure_local_user(db_session).id, name="python"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def _upgrade_to(engine, revision: str) -> None:
    with engine.connect() as connection:
        command.upgrade(_alembic_config(connection), revision)


def _seed_owned_rows(connection) -> None:
    now = "2026-10-31 00:00:00"
    connection.execute(
        text(
            "INSERT INTO pipes (id, name, spec_json, created_at, updated_at) "
            "VALUES (1, 'Pipe', '{}', :now, :now)"
        ),
        {"now": now},
    )
    connection.execute(
        text(
            "INSERT INTO feeds (id, url, title, kind, created_at) "
            "VALUES (1, 'https://example.com/feed.xml', 'Example', 'feed', :now)"
        ),
        {"now": now},
    )
    connection.execute(
        text(
            "INSERT INTO items (id, feed_id, guid, title, content, is_read, starred, fetched_at) "
            "VALUES (1, 1, 'item-1', 'One', '', 0, 0, :now)"
        ),
        {"now": now},
    )
    connection.execute(
        text("INSERT INTO labels (id, name, name_key) VALUES (1, 'Python', 'python')")
    )
    connection.execute(text("INSERT INTO item_labels (item_id, label_id) VALUES (1, 1)"))
    connection.execute(
        text(
            "INSERT INTO runs "
            "(id, pipe_id, started, status, result_count, steps_json, item_ids_json) "
            "VALUES (1, 1, :now, 'success', 1, '[]', '[1]')"
        ),
        {"now": now},
    )


def _unique_column_sets(engine, table: str) -> set[tuple[str, ...]]:
    inspector = inspect(engine)
    columns: set[tuple[str, ...]] = set()
    for constraint in inspector.get_unique_constraints(table):
        columns.add(tuple(constraint.get("column_names") or ()))
    for index in inspector.get_indexes(table):
        if index.get("unique"):
            columns.add(tuple(index.get("column_names") or ()))
    return columns


def test_ownership_migration_backfills_rows_and_adds_constraints(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ownership.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        _upgrade_to(engine, "0003_users")
        with engine.begin() as connection:
            _seed_owned_rows(connection)

        init_db(engine)

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            owner_id = connection.execute(
                text("SELECT id FROM users WHERE auth0_sub = 'local'")
            ).scalar_one()
            assert revision == HEAD_REVISION
            for table in ("feeds", "labels", "pipes"):
                stored = connection.execute(
                    text(f"SELECT owner_id FROM {table}")
                ).scalars()
                assert list(stored) == [owner_id]
            assert connection.execute(
                text("SELECT count(*) FROM items")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM runs")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM item_labels")
            ).scalar_one() == 1

        assert ("owner_id", "url") in _unique_column_sets(engine, "feeds")
        assert ("url",) not in _unique_column_sets(engine, "feeds")
        assert ("owner_id", "name_key") in _unique_column_sets(engine, "labels")
        assert ("name_key",) not in _unique_column_sets(engine, "labels")

        inspector = inspect(engine)
        for table in ("feeds", "labels", "pipes"):
            foreign_keys = inspector.get_foreign_keys(table)
            owner_fk = next(
                foreign_key
                for foreign_key in foreign_keys
                if foreign_key["constrained_columns"] == ["owner_id"]
            )
            assert owner_fk["referred_table"] == "users"
            assert owner_fk["options"].get("ondelete") == "CASCADE"
    finally:
        engine.dispose()


def test_ownership_migration_merges_duplicate_labels(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate-labels.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        _upgrade_to(engine, "0003_users")
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql(
                "CREATE TABLE labels_new ("
                "id INTEGER NOT NULL, "
                "name VARCHAR(100) NOT NULL, "
                "name_key VARCHAR(200) NOT NULL, "
                "CONSTRAINT pk_labels PRIMARY KEY (id))"
            )
            connection.exec_driver_sql(
                "INSERT INTO labels_new (id, name, name_key) VALUES "
                "(1, 'Python', 'python'), (2, 'python', 'python')"
            )
            connection.exec_driver_sql("DROP TABLE labels")
            connection.exec_driver_sql("ALTER TABLE labels_new RENAME TO labels")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

            now = "2026-10-31 00:00:00"
            connection.execute(
                text(
                    "INSERT INTO feeds (id, url, title, kind, created_at) "
                    "VALUES (1, 'https://example.com/feed.xml', 'Example', 'feed', :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO items "
                    "(id, feed_id, guid, title, content, is_read, starred, fetched_at) "
                    "VALUES (1, 1, 'one', 'One', '', 0, 0, :now), "
                    "(2, 1, 'two', 'Two', '', 0, 0, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO item_labels (item_id, label_id) VALUES (1, 1), (2, 2)"
                )
            )

        init_db(engine)

        with engine.connect() as connection:
            labels = connection.execute(
                text("SELECT id, name_key FROM labels")
            ).all()
            assert labels == [(1, "python")]
            links = connection.execute(
                text("SELECT item_id, label_id FROM item_labels ORDER BY item_id")
            ).all()
            assert links == [(1, 1), (2, 1)]
    finally:
        engine.dispose()


def test_ownership_downgrade_restores_global_uniqueness(tmp_path: Path) -> None:
    db_path = tmp_path / "ownership-downgrade.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        init_db(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, auth0_sub, name, created_at, last_seen_at) "
                    "VALUES (2, 'auth0|other', 'Other', :now, :now)"
                ),
                {"now": "2026-10-31 00:00:00"},
            )
            for owner_id in (1, 2):
                connection.execute(
                    text(
                        "INSERT INTO feeds (owner_id, url, title, kind, created_at) "
                        "VALUES (:owner_id, 'https://example.com/feed.xml', "
                        "'Example', 'feed', :now)"
                    ),
                    {"owner_id": owner_id, "now": "2026-10-31 00:00:00"},
                )
                connection.execute(
                    text(
                        "INSERT INTO labels (owner_id, name, name_key) "
                        "VALUES (:owner_id, 'Python', 'python')"
                    ),
                    {"owner_id": owner_id},
                )

        with engine.connect() as connection:
            command.downgrade(_alembic_config(connection), "0003_users")

        inspector = inspect(engine)
        for table in ("feeds", "labels", "pipes"):
            assert "owner_id" not in {
                column["name"] for column in inspector.get_columns(table)
            }
        assert ("url",) in _unique_column_sets(engine, "feeds")
        assert ("name_key",) in _unique_column_sets(engine, "labels")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM feeds")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM labels")
            ).scalar_one() == 1
    finally:
        engine.dispose()


def test_ownership_upgrade_without_rows_skips_the_local_anchor(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "empty-ownership.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        _upgrade_to(engine, "0003_users")
        _upgrade_to(engine, HEAD_REVISION)

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM users")
            ).scalar_one() == 0
            assert connection.execute(
                text("SELECT count(*) FROM feeds")
            ).scalar_one() == 0
    finally:
        engine.dispose()


def test_ownership_uniqueness_is_scoped_per_user(tmp_path: Path) -> None:
    db_path = tmp_path / "per-owner-unique.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    now = "2026-10-31 00:00:00"
    try:
        init_db(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (auth0_sub, name, created_at, last_seen_at) "
                    "VALUES ('auth0|other', 'Other', :now, :now)"
                ),
                {"now": now},
            )
            local_id = connection.execute(
                text("SELECT id FROM users WHERE auth0_sub = 'local'")
            ).scalar_one()
            other_id = connection.execute(
                text("SELECT id FROM users WHERE auth0_sub = 'auth0|other'")
            ).scalar_one()

            for owner_id in (local_id, other_id):
                connection.execute(
                    text(
                        "INSERT INTO feeds (owner_id, url, title, kind, created_at) "
                        "VALUES (:owner_id, 'https://example.com/feed.xml', "
                        "'Example', 'feed', :now)"
                    ),
                    {"owner_id": owner_id, "now": now},
                )
                connection.execute(
                    text(
                        "INSERT INTO labels (owner_id, name, name_key) "
                        "VALUES (:owner_id, 'Python', 'python')"
                    ),
                    {"owner_id": owner_id},
                )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO feeds (owner_id, url, title, kind, created_at) "
                    "VALUES (:owner_id, 'https://example.com/feed.xml', "
                    "'Again', 'feed', :now)"
                ),
                {"owner_id": local_id, "now": now},
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO labels (owner_id, name, name_key) "
                    "VALUES (:owner_id, 'python', 'python')"
                ),
                {"owner_id": local_id},
            )

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM feeds")
            ).scalar_one() == 2
            assert connection.execute(
                text("SELECT count(*) FROM labels")
            ).scalar_one() == 2
    finally:
        engine.dispose()


def test_ownership_upgrade_and_downgrade_tolerate_missing_label_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing-labels.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        _upgrade_to(engine, "0003_users")
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql("DROP TABLE item_labels")
            connection.exec_driver_sql("DROP TABLE labels")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

        _upgrade_to(engine, HEAD_REVISION)

        inspector = inspect(engine)
        assert "owner_id" in {
            column["name"] for column in inspector.get_columns("feeds")
        }
        assert "labels" not in inspector.get_table_names()

        with engine.connect() as connection:
            command.downgrade(_alembic_config(connection), "0003_users")

        inspector = inspect(engine)
        assert "owner_id" not in {
            column["name"] for column in inspector.get_columns("feeds")
        }
    finally:
        engine.dispose()


def test_legacy_database_without_labels_backfills_ownership(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-no-labels.db"
    settings = Settings(_env_file=None, db_path=db_path)
    engine = create_engine(settings)
    try:
        _stamp_baseline_only(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO feeds (id, url, title, kind, created_at) "
                    "VALUES (1, 'https://example.com/feed.xml', 'Example', 'feed', :now)"
                ),
                {"now": "2026-10-31 00:00:00"},
            )
            connection.execute(
                text(
                    "INSERT INTO items "
                    "(id, feed_id, guid, title, content, is_read, starred, fetched_at) "
                    "VALUES (1, 1, 'item-1', 'One', '', 0, 0, :now)"
                ),
                {"now": "2026-10-31 00:00:00"},
            )
            connection.exec_driver_sql("DROP TABLE item_labels")
            connection.exec_driver_sql("DROP TABLE labels")
        _remove_alembic_version(engine)

        init_db(engine)

        with engine.connect() as connection:
            owner_id = connection.execute(
                text("SELECT id FROM users WHERE auth0_sub = 'local'")
            ).scalar_one()
            assert connection.execute(
                text("SELECT owner_id FROM feeds")
            ).scalar_one() == owner_id
            assert connection.execute(
                text("SELECT count(*) FROM items")
            ).scalar_one() == 1
            label_columns = {
                column["name"] for column in inspect(engine).get_columns("labels")
            }
            assert "owner_id" in label_columns
    finally:
        engine.dispose()

