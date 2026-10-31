from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..models import Feed, Item, Pipe, pipe_feed_items
from .pipe_runs import execute_pipe

__all__ = [
    "PipeFeedResult",
    "add_pipe_feed",
    "pipe_feed_url",
    "refresh_pipe_feed",
]


@dataclass(slots=True)
class PipeFeedResult:
    feed: Feed | None
    created: bool
    items: int
    seconds: float
    error: str | None = None


def pipe_feed_url(pipe_id: int) -> str:
    """Return the synthetic URL that identifies a pipe's reader feed."""

    return f"pipe://{pipe_id}"


def add_pipe_feed(
    session: Session,
    pipe: Pipe,
    *,
    settings: Settings,
    client: httpx.Client | None = None,
) -> PipeFeedResult:
    """Run a pipe and add its output to the reader as a feed."""

    existing = session.scalar(
        select(Feed).where(Feed.owner_id == pipe.owner_id, Feed.pipe_id == pipe.id)
    )
    if existing is not None:
        return PipeFeedResult(
            feed=existing,
            created=False,
            items=_membership_count(session, existing.id),
            seconds=0.0,
            error=existing.last_error,
        )

    pipe_name = pipe.name or f"Pipe {pipe.id}"
    execution = execute_pipe(session, settings, pipe, client=client)
    if execution.error or execution.run is None:
        return PipeFeedResult(
            feed=None,
            created=False,
            items=0,
            seconds=execution.run.seconds if execution.run is not None else 0.0,
            error=execution.error or "Pipe run failed.",
        )

    feed = Feed(
        owner_id=pipe.owner_id,
        url=pipe_feed_url(pipe.id),
        title=pipe_name[:500],
        kind="pipe",
        pipe_id=pipe.id,
        last_fetched=utcnow(),
        last_error=None,
    )
    session.add(feed)
    session.flush()
    _replace_membership(session, feed, execution.item_ids)
    session.commit()
    session.refresh(feed)

    return PipeFeedResult(
        feed=feed,
        created=True,
        items=len(execution.item_ids),
        seconds=execution.run.seconds or 0.0,
    )


def refresh_pipe_feed(
    session: Session,
    feed: Feed,
    *,
    settings: Settings,
    client: httpx.Client | None = None,
) -> PipeFeedResult:
    """Run a pipe feed again and replace its membership in place."""

    if feed.pipe_id is None:
        return PipeFeedResult(
            feed=feed,
            created=False,
            items=0,
            seconds=0.0,
            error="This feed is not linked to a pipe.",
        )

    pipe = session.get(Pipe, feed.pipe_id)
    if pipe is None:
        return PipeFeedResult(
            feed=feed,
            created=False,
            items=0,
            seconds=0.0,
            error="The pipe for this feed no longer exists.",
        )
    if pipe.owner_id != feed.owner_id:
        return PipeFeedResult(
            feed=feed,
            created=False,
            items=0,
            seconds=0.0,
            error="The pipe for this feed belongs to another reader.",
        )

    feed_id = feed.id
    pipe_name = pipe.name or f"Pipe {pipe.id}"
    execution = execute_pipe(session, settings, pipe, client=client)

    feed = session.get(Feed, feed_id)
    if feed is None:  # pragma: no cover - the row was just loaded
        return PipeFeedResult(
            feed=None,
            created=False,
            items=0,
            seconds=execution.run.seconds if execution.run is not None else 0.0,
            error=execution.error or "The pipe feed disappeared.",
        )

    if execution.error or execution.run is None:
        feed.last_fetched = utcnow()
        feed.last_error = execution.error or "Pipe run failed."
        session.commit()
        session.refresh(feed)
        return PipeFeedResult(
            feed=feed,
            created=False,
            items=_membership_count(session, feed.id),
            seconds=execution.run.seconds if execution.run is not None else 0.0,
            error=feed.last_error,
        )

    feed.title = pipe_name[:500]
    feed.last_fetched = utcnow()
    feed.last_error = None
    _replace_membership(session, feed, execution.item_ids)
    session.commit()
    session.refresh(feed)

    return PipeFeedResult(
        feed=feed,
        created=False,
        items=len(execution.item_ids),
        seconds=execution.run.seconds or 0.0,
    )


def _replace_membership(session: Session, feed: Feed, item_ids: list[int]) -> None:
    """Replace a pipe feed's ordered membership without copying items."""

    session.execute(delete(pipe_feed_items).where(pipe_feed_items.c.feed_id == feed.id))
    unique_ids = list(dict.fromkeys(item_id for item_id in item_ids if item_id > 0))
    if not unique_ids:
        session.flush()
        return

    existing_ids = set(
        session.scalars(
            select(Item.id)
            .join(Item.feed)
            .where(Item.id.in_(unique_ids), Feed.owner_id == feed.owner_id)
        ).all()
    )
    rows = [
        {"feed_id": feed.id, "item_id": item_id, "position": position}
        for position, item_id in enumerate(unique_ids)
        if item_id in existing_ids
    ]
    if rows:
        session.execute(insert(pipe_feed_items), rows)
    session.flush()


def _membership_count(session: Session, feed_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(pipe_feed_items)
            .where(pipe_feed_items.c.feed_id == feed_id)
        )
        or 0
    )
