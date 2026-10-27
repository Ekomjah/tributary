from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from ..models import Feed
from ..schemas import FeedCreate, FeedOut, FeedRefreshOut
from ..services import feeds
from .deps import DbSession

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.get("", response_model=list[FeedOut])
def list_feeds(db: DbSession) -> list[Feed]:
    return list(db.scalars(select(Feed).order_by(Feed.title, Feed.url)).all())


@router.post("", response_model=FeedOut, status_code=status.HTTP_201_CREATED)
def create_feed(payload: FeedCreate, db: DbSession) -> Feed:
    url = feeds.normalize_url(payload.url)
    existing = db.scalar(select(Feed).where(Feed.url == url))
    if existing is not None:
        raise HTTPException(status_code=409, detail="That feed is already subscribed")

    feed = Feed(url=url, title=(payload.title or "").strip())
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


@router.post("/refresh", response_model=list[FeedRefreshOut])
def refresh_all(request: Request) -> list[FeedRefreshOut]:
    results = feeds.refresh_feeds(
        request.app.state.session_factory,
        request.app.state.settings,
    )
    return [FeedRefreshOut.model_validate(result) for result in results]


@router.get("/{feed_id}", response_model=FeedOut)
def get_feed(feed_id: int, db: DbSession) -> Feed:
    feed = db.get(Feed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feed(feed_id: int, db: DbSession) -> Response:
    feed = db.get(Feed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    db.delete(feed)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{feed_id}/refresh", response_model=FeedRefreshOut)
def refresh_feed(feed_id: int, request: Request, db: DbSession) -> FeedRefreshOut:
    feed = db.get(Feed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    with feeds.make_client(request.app.state.settings) as client:
        result = feeds.fetch_feed(db, feed.url, client=client)
    db.commit()
    return FeedRefreshOut.model_validate(result)
