from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow

item_labels = Table(
    "item_labels",
    Base.metadata,
    Column("item_id", ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)


class Feed(Base):
    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="feed", index=True)
    last_fetched: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    etag: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    items: Mapped[list[Item]] = relationship(
        back_populates="feed",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"Feed(id={self.id!r}, url={self.url!r}, title={self.title!r})"


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("feed_id", "guid", name="uq_items_feed_guid"),
        CheckConstraint("decision IN ('keep', 'drop') OR decision IS NULL", name="decision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_id: Mapped[int] = mapped_column(
        ForeignKey("feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guid: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    published: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cover_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_alt: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fetch_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_care: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    decision: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    feed: Mapped[Feed] = relationship(back_populates="items")
    labels: Mapped[list[Label]] = relationship(
        secondary=item_labels,
        back_populates="items",
        lazy="selectin",
    )
    box_cache: Mapped[list[BoxCache]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"Item(id={self.id!r}, title={self.title!r}, decision={self.decision!r})"


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(100, collation="NOCASE"),
        unique=True,
        nullable=False,
    )

    items: Mapped[list[Item]] = relationship(
        secondary=item_labels,
        back_populates="labels",
    )

    def __repr__(self) -> str:
        return f"Label(id={self.id!r}, name={self.name!r})"


class Pipe(Base):
    __tablename__ = "pipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    runs: Mapped[list[Run]] = relationship(
        back_populates="pipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"Pipe(id={self.id!r}, name={self.name!r})"


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'success', 'error')", name="status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipe_id: Mapped[int] = mapped_column(
        ForeignKey("pipes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    pipe: Mapped[Pipe] = relationship(back_populates="runs")

    def __repr__(self) -> str:
        return f"Run(id={self.id!r}, pipe_id={self.pipe_id!r}, status={self.status!r})"


class BoxCache(Base):
    __tablename__ = "box_cache"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    box: Mapped[str] = mapped_column(String(50), primary_key=True)
    params_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True, default="")
    output: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    item: Mapped[Item] = relationship(back_populates="box_cache")

    def __repr__(self) -> str:
        return (
            f"BoxCache(item_id={self.item_id!r}, box={self.box!r}, "
            f"params_hash={self.params_hash!r}, model={self.model!r})"
        )


class SearchCache(Base):
    __tablename__ = "search_cache"

    params_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"SearchCache(params_hash={self.params_hash!r})"
