from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Feed, Item, Label, Pipe, Run


def _missing(kind: str) -> HTTPException:
    # Cross-tenant IDs deliberately look identical to missing IDs, so callers
    # cannot probe which rows belong to another user.
    return HTTPException(status_code=404, detail=f"{kind} not found")


def owned_feed(db: Session, owner_id: int, feed_id: int) -> Feed:
    feed = db.scalar(
        select(Feed).where(Feed.id == feed_id, Feed.owner_id == owner_id)
    )
    if feed is None:
        raise _missing("Feed")
    return feed


def owned_item(db: Session, owner_id: int, item_id: int) -> Item:
    item = db.scalar(
        select(Item)
        .join(Feed, Feed.id == Item.feed_id)
        .where(Item.id == item_id, Feed.owner_id == owner_id)
    )
    if item is None:
        raise _missing("Item")
    return item


def owned_label(db: Session, owner_id: int, label_id: int) -> Label:
    label = db.scalar(
        select(Label).where(Label.id == label_id, Label.owner_id == owner_id)
    )
    if label is None:
        raise _missing("Label")
    return label


def owned_pipe(db: Session, owner_id: int, pipe_id: int) -> Pipe:
    pipe = db.scalar(
        select(Pipe).where(Pipe.id == pipe_id, Pipe.owner_id == owner_id)
    )
    if pipe is None:
        raise _missing("Pipe")
    return pipe


def owned_run(db: Session, owner_id: int, run_id: int) -> Run:
    run = db.scalar(
        select(Run)
        .join(Pipe, Pipe.id == Run.pipe_id)
        .where(Run.id == run_id, Pipe.owner_id == owner_id)
    )
    if run is None:
        raise _missing("Run")
    return run
