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
from sentry_sdk import logger as sentry_logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..db import session_scope, utcnow
from ..models import Feed, Item
from .jsonfeed import JsonFeedError, parse_json_feed
from .text import (
    clean_byline,
    html_to_text,
    is_promo_image,
    leading_image,
    normalize_text,
    readable_title,
    safe_image_url,
    sanitize_html,
    strip_leading_image,
)
from .urls import redact_url, redact_urls_in_text, validate_public_url

logger = logging.getLogger(__name__)

__all__ = [
    "Download",
    "FeedFetchError",
    "FeedParseError",
    "FetchResult",
    "add_feed",
    "download_url",
    "fetch_feed",
    "make_client",
    "normalize_url",
    "parse_feed",
    "refresh_feeds",
    "store_entries",
]

_MAX_REDIRECTS = 5
_MAX_FEED_BYTES = 2_000_000
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_IMAGE_SUFFIXES = (".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp")


class FeedFetchError(RuntimeError):
    """A feed download failed in a way that is safe to show to the user."""


class FeedParseError(ValueError):
    """A response was not a usable feed."""


@dataclass(slots=True)
class Download:
    """A validated feed response, after any redirects."""

    url: str
    status_code: int
    headers: httpx.Headers
    content: bytes = b""


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
        follow_redirects=False,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": (
                "application/atom+xml, application/rss+xml, application/feed+json, "
                "application/xml, text/xml, */*"
            ),
        },
    )


def download_url(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_bytes: int = _MAX_FEED_BYTES,
) -> Download:
    """Download a feed while following redirects manually.

    Every hop is checked by :func:`validate_public_url` *before* a request is
    made, so a public URL cannot redirect the fetcher into a private network.
    """

    current = normalize_url(url)
    seen: set[str] = set()
    request_headers = headers or {}

    for _ in range(_MAX_REDIRECTS + 1):
        validate_public_url(current)
        with client.stream(
            "GET",
            current,
            headers=request_headers,
            follow_redirects=False,
        ) as response:
            status_code = response.status_code

            if status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise FeedFetchError("redirect response without a Location header")
                next_url = normalize_url(urljoin(current, location))
                if next_url == current or next_url in seen:
                    raise FeedFetchError("redirect loop")
                seen.add(current)
                current = next_url
                continue

            if status_code == 304:
                return Download(
                    url=str(response.url),
                    status_code=304,
                    headers=response.headers,
                )

            if status_code in {202, 204}:
                raise FeedFetchError(f"feed endpoint returned HTTP {status_code} without content")

            if not 200 <= status_code < 300:
                response.raise_for_status()
                raise FeedFetchError(f"feed endpoint returned HTTP {status_code}")

            buffer = bytearray()
            for chunk in response.iter_bytes():
                remaining = max_bytes - len(buffer)
                if remaining <= 0:
                    raise FeedFetchError(f"feed response exceeded {max_bytes} bytes")
                buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    raise FeedFetchError(f"feed response exceeded {max_bytes} bytes")

            return Download(
                url=str(response.url),
                status_code=status_code,
                headers=response.headers,
                content=bytes(buffer),
            )

    raise FeedFetchError("too many redirects")


def parse_feed(content: bytes) -> feedparser.FeedParserDict:
    """Parse bytes and reject responses that are not actually feeds."""

    if not content.strip():
        raise FeedParseError("empty feed response")

    stripped = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"{"):
        try:
            return parse_json_feed(content)
        except JsonFeedError as exc:
            raise FeedParseError(str(exc)) from exc

    parsed = feedparser.parse(content)
    version = str(parsed.get("version") or "")
    metadata = parsed.get("feed") or {}
    title = str(metadata.get("title") or "").strip()
    link = str(metadata.get("link") or "").strip()

    if not version and not parsed.entries and not (title or link):
        raise FeedParseError("response is not a feed")

    return parsed


def fetch_feed(
    session: Session,
    url: str,
    *,
    client: httpx.Client,
    min_full_chars: int = 500,
) -> FetchResult:
    """Fetch one feed, store new items, and record the outcome.

    Network and parse failures are recorded on an existing feed and returned in
    the result instead of raised, so a refresh can continue with the next feed.
    A failed first fetch creates no feed row.
    """

    canonical_url = normalize_url(url)
    started = time.perf_counter()

    with sentry_sdk.start_span(
        op="feed.fetch",
        name=urlsplit(canonical_url).hostname or "feed",
    ) as span:
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

    headers: dict[str, str] = {}
    if feed is not None:
        if feed.etag:
            headers["If-None-Match"] = feed.etag
        if feed.last_modified:
            headers["If-Modified-Since"] = feed.last_modified

    try:
        download = download_url(client, url, headers=headers)
    except Exception as exc:
        return _record_error(feed, url, exc)

    if download.status_code == 304:
        if feed is None:
            return _record_error(
                None,
                url,
                FeedFetchError("unexpected 304 response for a new feed"),
            )
        feed.last_fetched = utcnow()
        feed.last_error = None
        _update_validators(feed, download.headers)
        return FetchResult(
            url=url,
            feed_id=feed.id,
            title=feed.title,
            not_modified=True,
        )

    try:
        parsed = parse_feed(download.content)
    except Exception as exc:
        return _record_error(feed, url, exc)

    if feed is None:
        feed = Feed(url=url, title="")
        session.add(feed)
        session.flush()

    return _store_parsed(
        session,
        feed,
        parsed,
        download,
        min_full_chars=min_full_chars,
    )


def add_feed(
    session: Session,
    url: str,
    *,
    client: httpx.Client,
    title: str | None = None,
    min_full_chars: int = 500,
) -> tuple[Feed, FetchResult]:
    """Validate a feed URL, create it, and ingest its entries in one request.

    The row is created only after the response has been downloaded and parsed.
    Network, unsafe-URL, and parse failures are raised for the API to map to the
    right status code; nothing is written in that case.
    """

    canonical_url = normalize_url(url)
    download = download_url(client, canonical_url)
    if download.status_code == 304:
        raise FeedFetchError("unexpected 304 response for a new feed")

    parsed = parse_feed(download.content)

    feed = Feed(url=canonical_url, title="")
    session.add(feed)
    session.flush()

    result = _store_parsed(
        session,
        feed,
        parsed,
        download,
        min_full_chars=min_full_chars,
        title_override=title,
    )
    return feed, result


def _store_parsed(
    session: Session,
    feed: Feed,
    parsed: feedparser.FeedParserDict,
    download: Download,
    *,
    min_full_chars: int,
    title_override: str | None = None,
) -> FetchResult:
    title = readable_title(str(parsed.feed.get("title") or "")).strip()
    override = (title_override or "").strip()
    if override:
        title = override
    if title:
        feed.title = title[:500]
    elif not feed.title:
        feed.title = feed.url[:500]

    _update_validators(feed, download.headers)
    feed.last_fetched = utcnow()
    feed.last_error = None

    entries = list(parsed.entries)
    new_items = store_entries(
        session,
        feed,
        entries,
        feed_url=download.url,
        min_full_chars=min_full_chars,
    )

    return FetchResult(
        url=feed.url,
        feed_id=feed.id,
        title=feed.title,
        new_items=new_items,
        total_entries=len(entries),
    )


def store_entries(
    session: Session,
    feed: Feed,
    entries: list[Any],
    *,
    feed_url: str,
    min_full_chars: int = 500,
) -> int:
    """Store unseen entries, using the final feed URL for relative links."""

    existing_guids = set(session.scalars(select(Item.guid).where(Item.feed_id == feed.id)).all())
    now = utcnow()
    new_items = 0

    for entry in entries:
        link = _entry_link(entry, feed_url)
        guid = _entry_guid(entry, link)
        if not guid or guid in existing_guids:
            continue

        content, full_text = _entry_text(entry)
        has_full_text = bool(full_text and len(full_text) >= min_full_chars)
        base_url = link or feed_url
        content_html = _entry_html(entry, base_url)
        cover_image, cover_image_alt, cover_caption = _entry_cover(
            entry,
            content_html,
            base_url,
        )
        if content_html and cover_image:
            content_html, stripped_caption = strip_leading_image(content_html, cover_image)
            cover_caption = stripped_caption or cover_caption

        session.add(
            Item(
                feed_id=feed.id,
                guid=guid,
                title=readable_title(str(entry.get("title") or "")).strip()[:1000],
                link=link,
                published=_entry_published(entry),
                content=content,
                content_html=content_html,
                author=_entry_author(entry),
                cover_image=cover_image,
                cover_image_alt=cover_image_alt,
                cover_caption=cover_caption,
                content_full=full_text if has_full_text else None,
                fetch_status="ok" if has_full_text else None,
                content_fetched_at=now if has_full_text else None,
                fetched_at=now,
            )
        )
        existing_guids.add(guid)
        new_items += 1

    return new_items


def refresh_feeds(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> list[FetchResult]:
    """Refresh every subscribed feed, isolating failures per feed."""

    with session_factory() as session:
        urls = list(
            session.scalars(select(Feed.url).where(Feed.kind != "search").order_by(Feed.id)).all()
        )

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
                    error = _format_error(exc)
                    logger.error(
                        "Unexpected error while refreshing %s: %s",
                        redact_url(url),
                        error,
                    )
                    results.append(FetchResult(url=url, error=error))
                    _mark_feed_error(session_factory, url, exc)
    finally:
        if owns_client:
            active_client.close()

    _record_refresh_metrics(results, (time.perf_counter() - started) * 1000)
    return results


def _update_validators(feed: Feed, headers: httpx.Headers) -> None:
    etag = headers.get("etag")
    if etag:
        feed.etag = etag
    last_modified = headers.get("last-modified")
    if last_modified:
        feed.last_modified = last_modified


def _record_error(feed: Feed | None, url: str, exc: Exception) -> FetchResult:
    error = _format_error(exc)
    safe_url = redact_url(url)

    if feed is not None:
        feed.last_error = error
        feed.last_fetched = utcnow()

    logger.warning("Feed fetch failed for %s: %s", safe_url, error)

    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("feed.url", safe_url)
            scope.set_context("feed", {"url": safe_url, "error": error})
            sentry_sdk.capture_exception(FeedFetchError(error))
            sentry_logger.warning(
                "Feed fetch failed for {url}",
                url=safe_url,
                attributes={"feed.url": safe_url, "error.type": type(exc).__name__},
            )
    except Exception:  # pragma: no cover - telemetry must never break fetching
        logger.debug("Sentry error capture failed", exc_info=True)

    return FetchResult(
        url=url,
        feed_id=feed.id if feed is not None else None,
        title=feed.title if feed is not None else "",
        error=error,
    )


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
        logger.error(
            "Could not record the fetch error for %s: %s",
            redact_url(url),
            _format_error(exc),
        )


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

    title = readable_title(str(entry.get("title") or "")).strip()
    published = str(entry.get("published") or entry.get("updated") or "").strip()
    content, _full_text = _entry_text(entry)
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


def _entry_text(entry: Any) -> tuple[str, str | None]:
    """Return the display text and, when present, real full-text content.

    Only ``content:encoded`` (RSS) or Atom ``<content>`` counts as full text.
    A long ``<description>`` is still just a summary, so the article extractor
    will fetch the page instead of treating it as the finished article.
    """

    content = _entry_content(entry)
    if content is not None:
        raw_content, content_type = content
        if content_type == "text/plain":
            full_text = normalize_text(raw_content).strip()
        else:
            full_text = html_to_text(raw_content)
        return full_text, full_text

    raw_summary = str(entry.get("summary") or entry.get("description") or "")
    return html_to_text(raw_summary), None


def _entry_html(entry: Any, base_url: str) -> str | None:
    """Return the sanitized display copy for an entry, when it has markup.

    The HTML must describe the same body as ``_entry_text``. A text/plain
    content body therefore returns ``None`` instead of falling back to the
    summary, which would make the reader show a short summary in place of the
    full text. The entry's image is stored as frontmatter instead of being
    injected into the body, so the reader can render it once as a cover.
    """

    content = _entry_content(entry)
    if content is not None:
        raw_content, content_type = content
        if content_type == "text/plain":
            return None
        return sanitize_html(raw_content, base_url=base_url)

    raw_summary = str(entry.get("summary") or entry.get("description") or "")
    if not raw_summary.strip():
        return None
    return sanitize_html(raw_summary, base_url=base_url)


def _entry_author(entry: Any) -> str | None:
    """Return the writer named by an entry, when it has one."""

    for key in ("author", "dc_creator"):
        author = clean_byline(str(entry.get(key) or ""))
        if author:
            return author

    for item in _as_list(entry.get("authors")):
        if isinstance(item, dict):
            author = clean_byline(str(item.get("name") or ""))
            if author:
                return author
    return None


def _entry_cover(
    entry: Any,
    content_html: str | None,
    base_url: str,
) -> tuple[str | None, str | None, str | None]:
    """Pick the lead image, preferring the one already at the top of the body."""

    leading = leading_image(content_html)
    if leading is not None:
        return leading

    image = safe_image_url(_entry_image(entry), base_url=base_url)
    if image is None or is_promo_image(image):
        return None, None, None
    return image, None, None


def _entry_image(entry: Any) -> str | None:
    """Return the best image URL advertised by the entry, when there is one."""

    for item in _as_list(entry.get("media_content")):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        media_type = str(item.get("type") or "").lower()
        medium = str(item.get("medium") or "").lower()
        if url and (
            media_type.startswith("image/")
            or medium == "image"
            or _looks_like_image_url(url)
        ):
            return url

    for item in _as_list(entry.get("media_thumbnail")):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("href") or "").strip()
        if url:
            return url

    for item in _as_list(entry.get("enclosures")):
        if not isinstance(item, dict):
            continue
        url = str(item.get("href") or item.get("url") or "").strip()
        media_type = str(item.get("type") or "").lower()
        if url and (media_type.startswith("image/") or _looks_like_image_url(url)):
            return url

    image = entry.get("image")
    if isinstance(image, str) and image.strip():
        return image.strip()
    if isinstance(image, dict):
        url = str(image.get("href") or image.get("url") or "").strip()
        if url:
            return url
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _looks_like_image_url(value: str) -> bool:
    return urlsplit(value).path.lower().endswith(_IMAGE_SUFFIXES)


def _entry_content(entry: Any) -> tuple[str, str] | None:
    """Return the raw content value and its declared type, when present."""

    content = entry.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("value"):
                return str(part["value"]), str(part.get("type") or "text/html")
    elif isinstance(content, dict) and content.get("value"):
        return str(content["value"]), str(content.get("type") or "text/html")
    return None


def _format_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return redact_urls_in_text(f"{type(exc).__name__}: {message}")[:4000]
