"""Add hosted-account usage events for rolling quotas.

Revision ID: 0005_usage_events
Revises: 0004_ownership
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_usage_events"
down_revision: str | None = "0004_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_usage_events_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usage_events"),
    )
    op.create_index(
        "ix_usage_events_user_kind_created",
        "usage_events",
        ["user_id", "kind", "created_at"],
    )
    op.create_index(
        "ix_usage_events_created_at",
        "usage_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_index("ix_usage_events_user_kind_created", table_name="usage_events")
    op.drop_table("usage_events")
