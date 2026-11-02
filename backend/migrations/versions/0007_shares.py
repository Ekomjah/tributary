"""Add private article shares and shared-item provenance.

Revision ID: 0007_shares
Revises: 0006_item_discussion_meta
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_shares"
down_revision: str | None = "0006_item_discussion_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("source_item_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_by_id", sa.Integer(), nullable=True),
        sa.Column("claimed_item_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["claimed_by_id"],
            ["users.id"],
            name="fk_shares_claimed_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["claimed_item_id"],
            ["items.id"],
            name="fk_shares_claimed_item_id_items",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["users.id"],
            name="fk_shares_sender_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_item_id"],
            ["items.id"],
            name="fk_shares_source_item_id_items",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shares"),
        sa.UniqueConstraint("token_hash", name="uq_shares_token_hash"),
    )
    op.create_index("ix_shares_sender_id", "shares", ["sender_id"])
    op.create_index("ix_shares_expires_at", "shares", ["expires_at"])

    with op.batch_alter_table("items") as batch_op:
        batch_op.add_column(sa.Column("shared_by", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("shared_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("origin_feed_title", sa.String(length=500), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_column("origin_feed_title")
        batch_op.drop_column("shared_at")
        batch_op.drop_column("shared_by")

    op.drop_index("ix_shares_expires_at", table_name="shares")
    op.drop_index("ix_shares_sender_id", table_name="shares")
    op.drop_table("shares")
