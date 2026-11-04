"""Add feed ingestion progress columns.

Revision ID: 0008_feed_ingestion
Revises: 0007_shares
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_feed_ingestion"
down_revision: str | None = "0007_shares"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("feeds") as batch_op:
        batch_op.add_column(
            sa.Column(
                "ingest_state",
                sa.String(length=16),
                nullable=False,
                server_default="ready",
            )
        )
        batch_op.add_column(
            sa.Column(
                "ingest_total",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "ingest_processed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("ingest_token", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("ingest_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("feeds") as batch_op:
        batch_op.drop_column("ingest_error")
        batch_op.drop_column("ingest_token")
        batch_op.drop_column("ingest_processed")
        batch_op.drop_column("ingest_total")
        batch_op.drop_column("ingest_state")
