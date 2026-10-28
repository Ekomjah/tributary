from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from ..models import Feed
from ..schemas import (
    FeedAddOut,
    FeedCandidateOut,
    FeedCreate,
    FeedDiscoverRequest,
    FeedDiscoveryOut,
    FeedOut,
    FeedRefreshOut,
)
from ..services import discovery, feeds
from ..services.urls import UnsafeUrlError
from .deps import DbSession

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.get("", response_model=list[FeedOut])
def list_feeds(db: DbSession) -> list[Feed]:
    return list(db.scalars(select(Feed).order_by(Feed.title, Feed.url)).all())


@router.post("", response_model=FeedAddOut, status_code=status.HTTP_201_CREATED)
def create_feed(payload: FeedCreate, request: Request, db: DbSession) -> FeedAddOut:
    url = feeds.normalize_url(payload.url)
    existing = db.scalar(select(Feed).where(Feed.url == url))
    if existing is not None:
        raise HTTPException(status_code=409, detail="That feed is already subscribed")

    settings = request.app.state.settings
    try:
        with feeds.make_client(settings) as client:
            feed, result = feeds.add_feed(
                db,
                url,
                client=client,
                title=payload.title,
                min_full_chars=settings.article_min_chars,
            )
    except UnsafeUrlError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except feeds.FeedParseError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="That URL did not return a feed.",
        ) from exc
    except feeds.FeedFetchError as exc:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Could not fetch that feed.",
        ) from exc
    except httpx.HTTPError as exc:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Could not reach that feed.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.commit()
    db.refresh(feed)
    return FeedAddOut(
        feed=FeedOut.model_validate(feed),
        result=FeedRefreshOut.model_validate(result),
    )


@router.post("/refresh", response_model=list[FeedRefreshOut])
def refresh_all(request: Request) -> list[FeedRefreshOut]:
    results = feeds.refresh_feeds(
        request.app.state.session_factory,
        request.app.state.settings,
    )
    return [FeedRefreshOut.model_validate(result) for result in results]


@router.post("/discover", response_model=FeedDiscoveryOut)
def discover_feed(payload: FeedDiscoverRequest, request: Request) -> FeedDiscoveryOut:
    settings = request.app.state.settings
    try:
        with feeds.make_client(settings) as client:
            result = discovery.discover_feed(client, payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (feeds.FeedFetchError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not reach that address.",
        ) from exc

    return FeedDiscoveryOut(
        input_url=result.input_url,
        page_title=result.page_title,
        candidates=[
            FeedCandidateOut(url=candidate.url, title=candidate.title, kind=candidate.kind)
            for candidate in result.candidates
        ],
    )


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
    if feed.kind == "search":
        raise HTTPException(
            status_code=400,
            detail="Search feeds refresh when you run the search again.",
        )

    settings = request.app.state.settings
    with feeds.make_client(settings) as client:
        result = feeds.fetch_feed(
            db,
            feed.url,
            client=client,
            min_full_chars=settings.article_min_chars,
        )
    db.commit()
    return FeedRefreshOut.model_validate(result)
