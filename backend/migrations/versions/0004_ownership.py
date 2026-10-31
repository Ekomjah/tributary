"""Scope feeds, labels and pipes to a user.

Revision ID: 0004_ownership
Revises: 0003_users
Create Date: 2026-10-31

Existing rows are assigned to the synthetic ``local`` user. Duplicate label
names are merged before the per-owner unique constraint is added. SQLite uses
batch table rebuilds; PostgreSQL uses normal ALTER statements.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ownership"
down_revision: str | None = "0003_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCAL_SUB = "local"
_OWNED_TABLES = ("feeds", "labels", "pipes")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_local_user(connection: sa.Connection) -> int:
    row = connection.execute(
        sa.text("SELECT id FROM users WHERE auth0_sub = :sub"),
        {"sub": _LOCAL_SUB},
    ).first()
    if row is not None:
        return int(row[0])

    now = _utcnow()
    connection.execute(
        sa.text(
            "INSERT INTO users (auth0_sub, email, name, created_at, last_seen_at) "
            "VALUES (:sub, NULL, :name, :created_at, :last_seen_at)"
        ),
        {
            "sub": _LOCAL_SUB,
            "name": "Local",
            "created_at": now,
            "last_seen_at": now,
        },
    )
    row = connection.execute(
        sa.text("SELECT id FROM users WHERE auth0_sub = :sub"),
        {"sub": _LOCAL_SUB},
    ).first()
    if row is None:  # pragma: no cover - defensive
        raise RuntimeError("Could not create the local user")
    return int(row[0])


def _columns(inspector: sa.Inspector, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspector.get_columns(table)}


def _foreign_key_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {
        str(fk["name"])
        for fk in inspector.get_foreign_keys(table)
        if fk.get("name")
    }


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspector.get_indexes(table)
        if index.get("name")
    }


def _unique_column_sets(inspector: sa.Inspector, table: str) -> set[tuple[str, ...]]:
    columns: set[tuple[str, ...]] = set()
    for constraint in inspector.get_unique_constraints(table):
        columns.add(tuple(constraint.get("column_names") or ()))
    for index in inspector.get_indexes(table):
        if index.get("unique"):
            columns.add(tuple(index.get("column_names") or ()))
    return columns


def _merge_duplicate_labels(connection: sa.Connection) -> None:
    """Keep the first label in each owner/name group and move associations."""

    tables = set(sa.inspect(connection).get_table_names())
    if "labels" not in tables:
        return
    has_links = "item_labels" in tables

    rows = connection.execute(
        sa.text("SELECT id, owner_id, name_key FROM labels ORDER BY id")
    ).fetchall()
    groups: dict[tuple[int, str], list[int]] = {}
    for label_id, owner_id, name_key in rows:
        groups.setdefault((int(owner_id), str(name_key)), []).append(int(label_id))

    for ids in groups.values():
        if len(ids) < 2:
            continue
        keeper, duplicates = ids[0], ids[1:]
        for duplicate in duplicates:
            if has_links:
                connection.execute(
                    sa.text(
                        "INSERT INTO item_labels (item_id, label_id) "
                        "SELECT item_id, :keeper FROM item_labels "
                        "WHERE label_id = :duplicate "
                        "AND item_id NOT IN ("
                        "  SELECT item_id FROM item_labels WHERE label_id = :keeper"
                        ")"
                    ),
                    {"keeper": keeper, "duplicate": duplicate},
                )
                connection.execute(
                    sa.text("DELETE FROM item_labels WHERE label_id = :duplicate"),
                    {"duplicate": duplicate},
                )
            connection.execute(
                sa.text("DELETE FROM labels WHERE id = :duplicate"),
                {"duplicate": duplicate},
            )


def _add_owner_column(table: str, inspector: sa.Inspector) -> None:
    if "owner_id" not in _columns(inspector, table):
        op.add_column(table, sa.Column("owner_id", sa.Integer(), nullable=True))


def _backfill_owner(connection: sa.Connection, table: str, owner_id: int) -> None:
    connection.execute(
        sa.text(
            f"UPDATE {table} SET owner_id = :owner_id WHERE owner_id IS NULL"
        ),
        {"owner_id": owner_id},
    )


def _sync_owner_column(
    table: str,
    *,
    unique_name: str | None = None,
    unique_columns: list[str] | None = None,
    old_unique_name: str | None = None,
    old_unique_columns: tuple[str, ...] | None = None,
) -> None:
    """Add the ownership FK, index and per-owner unique constraint."""

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if table not in inspector.get_table_names():
        return
    columns = _columns(inspector, table)
    fks = _foreign_key_names(inspector, table)
    indexes = _index_names(inspector, table)
    unique_sets = _unique_column_sets(inspector, table)

    fk_name = f"fk_{table}_owner_id_users"
    index_name = f"ix_{table}_owner_id"
    owner_unique = tuple(unique_columns or ())
    drop_old = (
        old_unique_name is not None
        and old_unique_columns is not None
        and old_unique_columns in unique_sets
    )
    need_owner_unique = bool(unique_columns) and owner_unique not in unique_sets
    need_not_null = bool(columns.get("owner_id", {}).get("nullable", False))
    need_fk = fk_name not in fks
    need_index = index_name not in indexes

    if not (need_not_null or need_fk or need_index or need_owner_unique or drop_old):
        return

    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(
            table,
            naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
        ) as batch:
            if need_not_null:
                batch.alter_column(
                    "owner_id",
                    existing_type=sa.Integer(),
                    nullable=False,
                )
            if need_fk:
                batch.create_foreign_key(
                    fk_name,
                    "users",
                    ["owner_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            if need_index:
                batch.create_index(index_name, ["owner_id"])
            if need_owner_unique and unique_name is not None and unique_columns:
                batch.create_unique_constraint(unique_name, unique_columns)
            if drop_old and old_unique_name is not None:
                batch.drop_constraint(old_unique_name, type_="unique")
        return

    if need_not_null:
        op.alter_column(
            table,
            "owner_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    if need_fk:
        op.create_foreign_key(
            fk_name,
            table,
            "users",
            ["owner_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if need_index:
        op.create_index(index_name, table, ["owner_id"])
    if need_owner_unique and unique_name is not None and unique_columns:
        op.create_unique_constraint(unique_name, table, unique_columns)
    if drop_old and old_unique_name is not None:
        op.drop_constraint(old_unique_name, table, type_="unique")


def _sqlite_foreign_keys(connection: sa.Connection, *, enabled: bool) -> None:
    """Toggle SQLite FK enforcement around batch table rebuilds.

    SQLite rebuilds a table by creating a new one, copying rows and dropping
    the old one. With foreign keys enabled, that drop cascades through
    ``items``, ``item_labels`` and ``runs``. Alembic's batch mode does not
    disable enforcement for us, so the migration does it explicitly.
    """

    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    _sqlite_foreign_keys(connection, enabled=False)
    try:
        _upgrade_ownership()
    finally:
        _sqlite_foreign_keys(connection, enabled=True)


def _tables_missing_owner(connection: sa.Connection, tables: list[str]) -> bool:
    """Return True when any existing owned table has rows to backfill."""

    for table in tables:
        count = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE owner_id IS NULL")
        ).scalar_one()
        if count:
            return True
    return False


def _upgrade_ownership() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        # A pre-Alembic database can be stamped at 0003 without the users
        # table; build the same shape here rather than failing later.
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("auth0_sub", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_users"),
        )
        op.create_index("ix_users_auth0_sub", "users", ["auth0_sub"], unique=True)
        tables.add("users")
        inspector = sa.inspect(connection)

    for table in _OWNED_TABLES:
        if table not in tables:
            continue
        _add_owner_column(table, inspector)
        inspector = sa.inspect(connection)

    owned_tables = [table for table in _OWNED_TABLES if table in tables]
    if _tables_missing_owner(connection, owned_tables):
        owner_id = _ensure_local_user(connection)
        for table in owned_tables:
            _backfill_owner(connection, table, owner_id)

    _merge_duplicate_labels(connection)

    for table in owned_tables:
        if table == "feeds":
            _sync_owner_column(
                "feeds",
                unique_name="uq_feeds_owner_url",
                unique_columns=["owner_id", "url"],
                old_unique_name="uq_feeds_url",
                old_unique_columns=("url",),
            )
        elif table == "labels":
            _sync_owner_column(
                "labels",
                unique_name="uq_labels_owner_name_key",
                unique_columns=["owner_id", "name_key"],
                old_unique_name="uq_labels_name_key",
                old_unique_columns=("name_key",),
            )
        else:
            _sync_owner_column(table)


def _drop_duplicate_rows(connection: sa.Connection) -> None:
    """Keep downgrade possible when two users share a URL or label name."""

    tables = set(sa.inspect(connection).get_table_names())
    if "feeds" in tables:
        connection.execute(
            sa.text(
                "DELETE FROM feeds WHERE id NOT IN ("
                "  SELECT MIN(id) FROM feeds GROUP BY url"
                ")"
            )
        )
    if "labels" not in tables:
        return
    if "item_labels" in tables:
        connection.execute(
            sa.text(
                "DELETE FROM item_labels WHERE label_id NOT IN ("
                "  SELECT MIN(id) FROM labels GROUP BY name_key"
                ")"
            )
        )
    connection.execute(
        sa.text(
            "DELETE FROM labels WHERE id NOT IN ("
            "  SELECT MIN(id) FROM labels GROUP BY name_key"
            ")"
        )
    )


def _restore_global_uniqueness(table: str) -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if table not in inspector.get_table_names():
        return
    fks = _foreign_key_names(inspector, table)
    indexes = _index_names(inspector, table)
    columns = _columns(inspector, table)
    unique_sets = _unique_column_sets(inspector, table)

    fk_name = f"fk_{table}_owner_id_users"
    index_name = f"ix_{table}_owner_id"
    owner_unique = (
        ("owner_id", "url") if table == "feeds" else
        ("owner_id", "name_key") if table == "labels" else None
    )
    owner_unique_name = {
        "feeds": "uq_feeds_owner_url",
        "labels": "uq_labels_owner_name_key",
    }.get(table)
    old_unique_name = "uq_feeds_url" if table == "feeds" else "uq_labels_name_key"
    old_unique_columns = ("url",) if table == "feeds" else ("name_key",)
    need_old_unique = table != "pipes" and old_unique_columns not in unique_sets
    need_drop_owner_unique = owner_unique is not None and owner_unique in unique_sets
    need_drop_fk = fk_name in fks
    need_drop_index = index_name in indexes
    need_drop_column = "owner_id" in columns

    if not (
        need_old_unique
        or need_drop_owner_unique
        or need_drop_fk
        or need_drop_index
        or need_drop_column
    ):
        return

    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            if need_drop_owner_unique:
                batch.drop_constraint(owner_unique_name, type_="unique")
            if need_drop_fk:
                batch.drop_constraint(fk_name, type_="foreignkey")
            if need_drop_index:
                batch.drop_index(index_name)
            if need_drop_column:
                batch.drop_column("owner_id")
            if table != "pipes" and need_old_unique:
                batch.create_unique_constraint(old_unique_name, list(old_unique_columns))
        return

    if need_drop_owner_unique:
        op.drop_constraint(owner_unique_name, table, type_="unique")
    if need_drop_fk:
        op.drop_constraint(fk_name, table, type_="foreignkey")
    if need_drop_index:
        op.drop_index(index_name, table_name=table)
    if need_drop_column:
        op.drop_column(table, "owner_id")
    if table != "pipes" and need_old_unique:
        op.create_unique_constraint(old_unique_name, table, list(old_unique_columns))


def downgrade() -> None:
    connection = op.get_bind()
    # Deduplicate with enforcement on so dropping a duplicate feed also
    # removes its items and memberships. The table rebuilds below need
    # enforcement off, or SQLite would cascade through every dependent row.
    _sqlite_foreign_keys(connection, enabled=True)
    _drop_duplicate_rows(connection)
    _sqlite_foreign_keys(connection, enabled=False)
    try:
        for table in ("feeds", "labels", "pipes"):
            _restore_global_uniqueness(table)
    finally:
        _sqlite_foreign_keys(connection, enabled=True)
