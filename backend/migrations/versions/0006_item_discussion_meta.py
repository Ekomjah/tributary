"""Add discussion metadata to feed items.

Revision ID: 0006_item_discussion_meta
Revises: 0005_usage_events
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_item_discussion_meta"
down_revision: str | None = "0005_usage_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch_op:
        batch_op.add_column(sa.Column("discussion_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("points", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("comment_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_column("comment_count")
        batch_op.drop_column("points")
        batch_op.drop_column("discussion_url")
