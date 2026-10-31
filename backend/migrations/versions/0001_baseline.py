"""Baseline schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pipes"),
    )

    op.create_table(
        "feeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("pipe_id", sa.Integer(), nullable=True),
        sa.Column("last_fetched", sa.DateTime(), nullable=True),
        sa.Column("etag", sa.String(length=500), nullable=True),
        sa.Column("last_modified", sa.String(length=200), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipe_id"],
            ["pipes.id"],
            name="fk_feeds_pipe_id_pipes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feeds"),
        sa.UniqueConstraint("url", name="uq_feeds_url"),
    )
    op.create_index("ix_feeds_kind", "feeds", ["kind"], unique=False)
    op.create_index("ix_feeds_pipe_id", "feeds", ["pipe_id"], unique=True)

    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("guid", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("published", sa.DateTime(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("cover_image", sa.Text(), nullable=True),
        sa.Column("cover_image_alt", sa.Text(), nullable=True),
        sa.Column("cover_caption", sa.Text(), nullable=True),
        sa.Column("content_full", sa.Text(), nullable=True),
        sa.Column("content_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("fetch_status", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("why_care", sa.Text(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.Column("decision", sa.String(length=8), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('keep', 'drop') OR decision IS NULL",
            name="ck_items_decision",
        ),
        sa.ForeignKeyConstraint(
            ["feed_id"],
            ["feeds.id"],
            name="fk_items_feed_id_feeds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_items"),
        sa.UniqueConstraint("feed_id", "guid", name="uq_items_feed_guid"),
    )
    op.create_index("ix_items_decision", "items", ["decision"], unique=False)
    op.create_index("ix_items_feed_id", "items", ["feed_id"], unique=False)
    op.create_index("ix_items_is_read", "items", ["is_read"], unique=False)
    op.create_index("ix_items_published", "items", ["published"], unique=False)
    op.create_index("ix_items_starred", "items", ["starred"], unique=False)

    op.create_table(
        "labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "name",
            sa.String(length=100),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_labels"),
        sa.UniqueConstraint("name", name="uq_labels_name"),
    )

    op.create_table(
        "item_labels",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_item_labels_item_id_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
            name="fk_item_labels_label_id_labels",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "label_id", name="pk_item_labels"),
    )

    op.create_table(
        "pipe_feed_items",
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["feed_id"],
            ["feeds.id"],
            name="fk_pipe_feed_items_feed_id_feeds",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_pipe_feed_items_item_id_items",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("feed_id", "item_id", name="pk_pipe_feed_items"),
    )
    op.create_index(
        "ix_pipe_feed_items_feed_position",
        "pipe_feed_items",
        ["feed_id", "position"],
        unique=False,
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipe_id", sa.Integer(), nullable=False),
        sa.Column("started", sa.DateTime(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_step", sa.Integer(), nullable=True),
        sa.Column("error_box", sa.String(length=50), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("item_ids_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'error')",
            name="ck_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["pipe_id"],
            ["pipes.id"],
            name="fk_runs_pipe_id_pipes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
    )
    op.create_index("ix_runs_pipe_id", "runs", ["pipe_id"], unique=False)

    op.create_table(
        "box_cache",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("box", sa.String(length=50), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_box_cache_item_id_items",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "box", "params_hash", "model", name="pk_box_cache"),
    )

    op.create_table(
        "search_cache",
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("params_hash", name="pk_search_cache"),
    )
    op.create_index(
        "ix_search_cache_expires_at",
        "search_cache",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_search_cache_expires_at", table_name="search_cache")
    op.drop_table("search_cache")
    op.drop_table("box_cache")
    op.drop_index("ix_runs_pipe_id", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_pipe_feed_items_feed_position", table_name="pipe_feed_items")
    op.drop_table("pipe_feed_items")
    op.drop_table("item_labels")
    op.drop_table("labels")
    op.drop_index("ix_items_starred", table_name="items")
    op.drop_index("ix_items_published", table_name="items")
    op.drop_index("ix_items_is_read", table_name="items")
    op.drop_index("ix_items_feed_id", table_name="items")
    op.drop_index("ix_items_decision", table_name="items")
    op.drop_table("items")
    op.drop_index("ix_feeds_pipe_id", table_name="feeds")
    op.drop_index("ix_feeds_kind", table_name="feeds")
    op.drop_table("feeds")
    op.drop_table("pipes")
