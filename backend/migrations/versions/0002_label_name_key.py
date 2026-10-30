"""Add a case-insensitive label name key.

Revision ID: 0002_label_name_key
Revises: 0001_baseline
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_label_name_key"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _name_key(name: str) -> str:
    return name.strip().casefold()


def upgrade() -> None:
    with op.batch_alter_table("labels") as batch_op:
        batch_op.add_column(sa.Column("name_key", sa.String(length=200), nullable=True))
        batch_op.drop_constraint("uq_labels_name", type_="unique")

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM labels")).fetchall()
    for label_id, name in rows:
        connection.execute(
            sa.text("UPDATE labels SET name_key = :name_key WHERE id = :label_id"),
            {"name_key": _name_key(name), "label_id": label_id},
        )

    with op.batch_alter_table("labels") as batch_op:
        batch_op.alter_column(
            "name_key",
            existing_type=sa.String(length=200),
            nullable=False,
        )
        batch_op.create_unique_constraint("uq_labels_name_key", ["name_key"])


def downgrade() -> None:
    with op.batch_alter_table("labels") as batch_op:
        batch_op.drop_constraint("uq_labels_name_key", type_="unique")
        batch_op.drop_column("name_key")
        batch_op.create_unique_constraint("uq_labels_name", ["name"])
