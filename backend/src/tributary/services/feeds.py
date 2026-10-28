from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import httpx
import sentry_sdk
import trafilatura
from sentry_sdk import logger as sentry_logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..db import session_scope, utcnow
from ..models import Feed, Item

logger = logging.getLogger(__name__)

__all__ = [
    "FetchResult",
    "fetch_feed",
    "make_client",
    "normalize_url",
    "refresh_feeds",
]


@dataclass(slots=True)
class FetchResult:
    """Outcome of fetching one feed."""

    url: str
    feed_id: int | None = None
    title: str = ""
    new_items: int = 0
    total_entries: int = 0
    not_modified: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def normalize_url(url: str) -> str:
    """Normalize a feed or item URL for stable storage and comparison.

    Fragments never reach a server, so they are dropped. The scheme and host are
    lowercased while the path and query stay untouched.
    """

    cleaned = url.strip()
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        return cleaned
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path or "/",
            parts.query,
            "",
        )
    )


def make_client(settings: Settings) -> httpx.Client:
    """Build the HTTP client used for feed downloads."""

    return httpx.Client(
        timeout=settings.fetch_timeout,
        follow_redirects=True,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": (
                "application/atom+xml, application/rss+xml, "
                "application/xml, text/xml, */*"
            ),
        },
    )


def fetch_feed(
    session: Session,
    url: str,
    *,
    client: httpx.Client,
    min_full_chars: int = 500,
) -> FetchResult:
    """Fetch one feed, store new items, and record the outcome.

    Network and parse failures are recorded on the feed and returned in the
    result instead of raised, so a refresh can continue with the next feed.
    """

    canonical_url = normalize_url(url)
    started = time.perf_counter()

    with sentry_sdk.start_span(op="feed.fetch", name=canonical_url) as span:
        result = _fetch_feed(
            session,
            canonical_url,
            client=client,
            min_full_chars=min_full_chars,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

        span.set_data("feed.new_items", result.new_items)
        span.set_data("feed.total_entries", result.total_entries)
        span.set_data("feed.not_modified", result.not_modified)
        if result.error:
            span.set_status("internal_error")

        _record_metrics(result, elapsed_ms)
        return result


def _fetch_feed(
    session: Session,
    url: str,
    *,
    client: httpx.Client,
    min_full_chars: int = 500,
) -> FetchResult:
    feed = session.scalar(select(Feed).where(Feed.url == url))
    if feed is None:
        feed = Feed(url=url, title="")
        session.add(feed)
        session.flush()

    headers: dict[str, str] = {}
    if feed.etag:
        headers["If-None-Match"] = feed.etag
    if feed.last_modified:
        headers["If-Modified-Since"] = feed.last_modified

    try:
        response = client.get(url, headers=headers)
        if response.status_code == 304:
            feed.last_fetched = utcnow()
            feed.last_error = None
            feed.etag = response.headers.get("etag", feed.etag)
            feed.last_modified = response.headers.get("last-modified", feed.last_modified)
            return FetchResult(
                url=url,
                feed_id=feed.id,
                title=feed.title,
                not_modified=True,
            )

        response.raise_for_status()
    except Exception as exc:
        return _record_error(feed, exc)

    try:
        parsed = feedparser.parse(response.content)
    except Exception as exc:
        return _record_error(feed, exc)

    entries = list(parsed.entries)
    if parsed.get("bozo") and not entries:
        exc = parsed.get("bozo_exception") or ValueError("feed could not be parsed")
        return _record_error(feed, exc)

    feed.title = str(parsed.feed.get("title") or feed.title or feed.url)[:500]
    feed.etag = response.headers.get("etag")
    feed.last_modified = response.headers.get("last-modified")
    feed.last_fetched = utcnow()
    feed.last_error = None

    existing_guids = set(
        session.scalars(select(Item.guid).where(Item.feed_id == feed.id)).all()
    )
    new_items = 0
    for entry in entries:
        link = _entry_link(entry, feed.url)
        guid = _entry_guid(entry, link)
        if not guid or guid in existing_guids:
            continue

        content = _entry_content(entry)
        has_full_text = len(content.strip()) >= min_full_chars
        session.add(
            Item(
                feed_id=feed.id,
                guid=guid,
                title=str(entry.get("title") or "")[:1000],
                link=link,
                published=_entry_published(entry),
                content=content,
                content_full=content if has_full_text else None,
                fetch_status="ok" if has_full_text else None,
                content_fetched_at=utcnow() if has_full_text else None,
                fetched_at=utcnow(),
            )
        )
        existing_guids.add(guid)
        new_items += 1

    return FetchResult(
        url=url,
        feed_id=feed.id,
        title=feed.title,
        new_items=new_items,
        total_entries=len(entries),
    )


def refresh_feeds(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> list[FetchResult]:
    """Refresh every subscribed feed, isolating failures per feed."""

    with session_factory() as session:
        urls = list(session.scalars(select(Feed.url).order_by(Feed.id)).all())

    if not urls:
        return []

    owns_client = client is None
    active_client = client or make_client(settings)
    results: list[FetchResult] = []
    started = time.perf_counter()

    try:
        with sentry_sdk.start_transaction(name="feed.refresh", op="task"):
            for url in urls:
                try:
                    with session_scope(session_factory) as session:
                        results.append(
                            fetch_feed(
                                session,
                                url,
                                client=active_client,
                                min_full_chars=settings.article_min_chars,
                            )
                        )
                except Exception as exc:
                    logger.exception("Unexpected error while refreshing %s", url)
                    results.append(FetchResult(url=url, error=_format_error(exc)))
                    _mark_feed_error(session_factory, url, exc)
    finally:
        if owns_client:
            active_client.close()

    _record_refresh_metrics(results, (time.perf_counter() - started) * 1000)
    return results


def _record_error(feed: Feed, exc: Exception) -> FetchResult:
    error = _format_error(exc)
    feed.last_error = error
    feed.last_fetched = utcnow()
    logger.warning("Feed fetch failed for %s: %s", feed.url, error)

    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("feed.url", feed.url)
            scope.set_context("feed", {"url": feed.url, "error": error})
            sentry_sdk.capture_exception(exc)
            sentry_logger.warning(
                "Feed fetch failed for {url}",
                url=feed.url,
                attributes={"feed.url": feed.url, "error.type": type(exc).__name__},
            )
    except Exception:  # pragma: no cover - telemetry must never break fetching
        logger.debug("Sentry error capture failed", exc_info=True)

    return FetchResult(url=feed.url, feed_id=feed.id, title=feed.title, error=error)


def _mark_feed_error(
    session_factory: sessionmaker[Session],
    url: str,
    exc: Exception,
) -> None:
    try:
        with session_scope(session_factory) as session:
            feed = session.scalar(select(Feed).where(Feed.url == url))
            if feed is not None:
                feed.last_error = _format_error(exc)
                feed.last_fetched = utcnow()
    except Exception:
        logger.exception("Could not record the fetch error for %s", url)


def _record_metrics(result: FetchResult, elapsed_ms: float) -> None:
    outcome = "error" if result.error else ("not_modified" if result.not_modified else "ok")
    try:
        sentry_sdk.metrics.count("feed.fetch", 1, attributes={"outcome": outcome})
        sentry_sdk.metrics.distribution(
            "feed.fetch.duration",
            elapsed_ms,
            unit="millisecond",
            attributes={"outcome": outcome},
        )
        if result.ok:
            sentry_sdk.metrics.distribution(
                "feed.items.new",
                result.new_items,
                attributes={"outcome": outcome},
            )
            sentry_sdk.metrics.distribution(
                "feed.items.entries",
                result.total_entries,
                attributes={"outcome": outcome},
            )
    except Exception:  # pragma: no cover - telemetry must never break fetching
        logger.debug("Sentry feed metrics failed", exc_info=True)


def _record_refresh_metrics(results: list[FetchResult], elapsed_ms: float) -> None:
    try:
        sentry_sdk.metrics.distribution(
            "feed.refresh.duration",
            elapsed_ms,
            unit="millisecond",
        )
        sentry_sdk.metrics.count(
            "feed.refresh.feeds",
            len(results),
            attributes={"outcome": "error" if any(r.error for r in results) else "ok"},
        )
    except Exception:  # pragma: no cover - telemetry must never break fetching
        logger.debug("Sentry refresh metrics failed", exc_info=True)


def _entry_link(entry: Any, feed_url: str) -> str | None:
    raw = entry.get("link")
    if not raw:
        return None
    return normalize_url(urljoin(feed_url, str(raw)))


def _entry_guid(entry: Any, link: str | None) -> str | None:
    raw = entry.get("id") or entry.get("guid")
    if raw:
        value = str(raw).strip()
        if value:
            return value

    if link:
        return link

    title = str(entry.get("title") or "").strip()
    published = str(entry.get("published") or entry.get("updated") or "").strip()
    content = _entry_content(entry)
    if not (title or published or content):
        return None

    digest = hashlib.sha256("\x00".join((title, published, content)).encode("utf-8")).hexdigest()
    return f"urn:tributary:{digest}"


def _entry_published(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if not parsed:
            continue
        try:
            return datetime(*tuple(parsed)[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _entry_content(entry: Any) -> str:
    content = entry.get("content")
    raw = ""
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("value"):
                raw = str(part["value"])
                break
    elif isinstance(content, dict) and content.get("value"):
        raw = str(content["value"])

    if not raw:
        raw = str(entry.get("summary") or entry.get("description") or "")

    return _readable_text(raw)


def _readable_text(raw: str) -> str:
    """Keep substantial feed HTML readable without fetching the article page.

    Short summaries stay untouched because the extractor needs enough prose to
    tell an article from navigation or boilerplate.
    """

    if "<" not in raw or len(raw) < 300:
        return raw

    try:
        extracted = trafilatura.extract(
            raw,
            include_comments=False,
            include_tables=False,
        )
    except Exception:  # pragma: no cover - malformed feed HTML
        return raw
    return extracted or raw


def _format_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return f"{type(exc).__name__}: {message}"[:4000]
