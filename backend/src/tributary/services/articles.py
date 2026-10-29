from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
import sentry_sdk
import trafilatura
from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..models import Item
from ..schemas import FetchStatus
from .text import (
    clean_byline,
    clean_meta_text,
    image_alt_for,
    is_promo_image,
    leading_image,
    safe_image_url,
    sanitize_html,
    strip_leading_image,
    titles_match,
)
from .urls import UnsafeUrlError, validate_public_url

logger = logging.getLogger(__name__)

__all__ = [
    "ArticleFetchError",
    "ArticleResult",
    "backfill_frontmatter",
    "fetch_article",
    "make_client",
]

_DOMAIN_LOCKS: dict[str, threading.Lock] = {}
_DOMAIN_LAST: dict[str, float] = {}
_DOMAIN_REGISTRY_LOCK = threading.Lock()

_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_METADATA_LABEL = re.compile(
    r"^(?:published|updated|last updated|posted)"
    r"(?:\s*(?:on\s+)?[:,-]?\s*(?:\d.*|today.*|yesterday.*|just now.*))?$"
    r"|^(?:share|save|comments)(?:\s*\(\d+\))?$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ArticleResult:
    """Outcome of trying to obtain one item's full text."""

    status: FetchStatus
    text: str | None = None
    html: str | None = None
    author: str | None = None
    cover_image: str | None = None
    cover_image_alt: str | None = None
    cover_caption: str | None = None
    fetched: bool = False
    truncated: bool = False
    bytes_read: int = 0
    error: str | None = None


@dataclass(slots=True)
class PageMetadata:
    """Structured frontmatter read from a page's own metadata tags."""

    author: str | None = None
    cover_image: str | None = None
    cover_image_alt: str | None = None


class ArticleFetchError(RuntimeError):
    """A sanitized article fetch failure safe to send to Sentry."""


def make_client(settings: Settings) -> httpx.Client:
    """Build the HTTP client used to fetch article pages."""

    return httpx.Client(
        timeout=settings.article_timeout,
        follow_redirects=False,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": _HTML_ACCEPT,
        },
    )


def fetch_article(
    session: Session,
    item: Item,
    *,
    settings: Settings,
    client: httpx.Client | None = None,
    force: bool = False,
) -> ArticleResult:
    """Populate ``item.content_full`` at most once, unless forced.

    Full text that came from a real ``content:encoded`` or Atom ``<content>``
    element is reused without a network request. Everything else, including a
    long ``<description>``, is fetched politely and cleaned with trafilatura.
    Every outcome is stored on the item so a paywall or a broken page is not
    retried on every refresh.
    """

    if not force and item.fetch_status is not None:
        text = item.content_full.strip() if item.content_full else None
        if text != item.content_full:
            item.content_full = text
            session.flush()
        return ArticleResult(
            status=item.fetch_status,  # type: ignore[arg-type]
            text=text,
            fetched=False,
        )

    if not force and item.content_full:
        text = item.content_full.strip()
        item.content_full = text
        item.fetch_status = "ok"
        if item.content_fetched_at is None:
            item.content_fetched_at = utcnow()
        session.flush()
        return ArticleResult(status="ok", text=text, fetched=False)

    if not item.link:
        return _store(session, item, ArticleResult(status="empty", error="no link"))

    host = urlsplit(item.link).hostname or "unknown"
    started = time.perf_counter()

    with sentry_sdk.start_span(op="article.fetch", name=host) as span:
        span.set_data("article.host", host)
        result = _fetch_page(
            item.link,
            host=host,
            title=item.title,
            settings=settings,
            client=client,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        span.set_data("article.status", result.status)
        span.set_data("article.bytes", result.bytes_read)
        span.set_data("article.chars", len(result.text or ""))
        span.set_data("article.html_chars", len(result.html or ""))
        span.set_data("article.truncated", result.truncated)
        span.set_data("article.duration_ms", round(elapsed_ms, 1))
        if result.status == "error":
            span.set_status("internal_error")
        _record_metrics(result, elapsed_ms)

    return _store(session, item, result)


def backfill_frontmatter(
    session: Session,
    *,
    settings: Settings,
    client: httpx.Client | None = None,
    limit: int | None = None,
) -> int:
    """Fill frontmatter on items whose full text was stored before it existed.

    ``fetch_article`` intentionally skips items that already have a fetch
    status, so older rows would never learn their writer or cover. This pass
    reads the page again and updates only the frontmatter and display HTML; the
    stored full text, fetch status and fetch timestamp stay untouched.
    """

    stmt = (
        select(Item)
        .where(
            Item.fetch_status == "ok",
            Item.link.is_not(None),
            or_(Item.author.is_(None), Item.cover_image.is_(None)),
        )
        .order_by(Item.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    items = list(session.scalars(stmt).all())
    if not items:
        return 0

    owns_client = client is None
    active_client = client or make_client(settings)
    updated = 0
    try:
        for item in items:
            link = item.link
            if not link:
                continue
            host = urlsplit(link).hostname or "unknown"
            try:
                result = _fetch_page(
                    link,
                    host=host,
                    title=item.title,
                    settings=settings,
                    client=active_client,
                )
            except Exception:  # pragma: no cover - a backfill must keep going
                logger.debug("Frontmatter backfill failed for item %s", item.id, exc_info=True)
                continue
            if result.status != "ok":
                continue
            if _apply_frontmatter(item, result):
                session.commit()
                updated += 1
    finally:
        if owns_client:
            active_client.close()
    return updated


def _apply_frontmatter(item: Item, result: ArticleResult) -> bool:
    """Copy a page's frontmatter onto an item without replacing its full text."""

    changed = False

    if result.author and result.author != item.author:
        item.author = result.author
        changed = True

    if result.cover_image:
        cover_changed = result.cover_image != item.cover_image
        item.cover_image = result.cover_image
        if cover_changed or result.cover_image_alt:
            item.cover_image_alt = result.cover_image_alt
            changed = True
        if cover_changed or result.cover_caption:
            item.cover_caption = result.cover_caption
            changed = True

        if item.content_html:
            stripped, caption = strip_leading_image(item.content_html, result.cover_image)
            if stripped != item.content_html:
                item.content_html = stripped
                changed = True
            if caption and not item.cover_caption:
                item.cover_caption = caption
                changed = True
        elif result.html:
            item.content_html = result.html
            changed = True
    elif result.html and not item.content_html:
        item.content_html = result.html
        changed = True

    return changed


def _fetch_page(
    url: str,
    *,
    host: str,
    title: str,
    settings: Settings,
    client: httpx.Client | None,
) -> ArticleResult:
    owns_client = client is None
    active_client = client or make_client(settings)
    response: httpx.Response | None = None

    try:
        try:
            response, final_url = _open_page(active_client, url, settings)
            _raise_for_status(response)
            if not _is_html(response):
                return ArticleResult(status="empty", error="not html")

            body, truncated = _read_capped(response, settings.article_max_bytes)
            if not body:
                return ArticleResult(status="empty", error="empty response")
        except httpx.HTTPStatusError as exc:
            status = _status_for_http(exc.response.status_code)
            _capture_error(exc, host=host, status=status)
            return ArticleResult(
                status=status,
                error=f"HTTP {exc.response.status_code}",
            )
        except UnsafeUrlError as exc:
            _capture_error(exc, host=host, status="error")
            return ArticleResult(status="error", error="unsafe url")
        except ArticleFetchError as exc:
            _capture_error(exc, host=host, status="error")
            return ArticleResult(status="error", error=str(exc))
        except httpx.HTTPError as exc:
            _capture_error(exc, host=host, status="error")
            return ArticleResult(status="error", error=type(exc).__name__)
        finally:
            if response is not None:
                response.close()

        try:
            extracted = trafilatura.extract(
                body,
                url=final_url,
                include_links=False,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            extracted_html = trafilatura.extract(
                body,
                url=final_url,
                output_format="html",
                include_links=True,
                include_comments=False,
                include_tables=True,
                include_images=True,
                include_formatting=True,
                favor_precision=True,
            )
        except Exception as exc:  # pragma: no cover - malformed page
            _capture_error(exc, host=host, status="error")
            return ArticleResult(
                status="error",
                truncated=truncated,
                bytes_read=len(body),
                error=type(exc).__name__,
            )

        text = _strip_leading_title((extracted or "").strip(), title)
        if len(text) < settings.article_min_chars:
            return ArticleResult(
                status="empty",
                text=None,
                truncated=truncated,
                bytes_read=len(body),
            )

        metadata = _extract_page_metadata(body, final_url)
        html = _strip_leading_heading(
            sanitize_html(extracted_html or "", base_url=final_url),
            title,
        )
        html = _strip_metadata_lists(html)
        cover_image, cover_image_alt, cover_caption = _choose_cover(html, metadata)
        if cover_image:
            html, stripped_caption = strip_leading_image(html, cover_image)
            cover_caption = stripped_caption or cover_caption

        return ArticleResult(
            status="ok",
            text=text,
            html=html,
            author=metadata.author,
            cover_image=cover_image,
            cover_image_alt=cover_image_alt,
            cover_caption=cover_caption,
            fetched=True,
            truncated=truncated,
            bytes_read=len(body),
        )
    finally:
        if owns_client:
            active_client.close()


def _open_page(
    client: httpx.Client,
    url: str,
    settings: Settings,
) -> tuple[httpx.Response, str]:
    """Open a page while validating every redirect hop before it is requested."""

    current = url
    seen: set[str] = set()

    for _ in range(_MAX_REDIRECTS + 1):
        validate_public_url(current)
        hop_host = urlsplit(current).hostname or "unknown"
        with _domain_lock(hop_host):
            _wait_for_domain(hop_host, settings.article_delay_seconds)
            request = client.build_request(
                "GET",
                current,
                timeout=settings.article_timeout,
                headers={"Accept": _HTML_ACCEPT},
            )
            try:
                response = client.send(request, stream=True, follow_redirects=False)
            finally:
                _DOMAIN_LAST[hop_host] = time.monotonic()

        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise ArticleFetchError("redirect response without a Location header")
            next_url = urljoin(current, location)
            if next_url == current or next_url in seen:
                raise ArticleFetchError("redirect loop")
            seen.add(current)
            current = next_url
            continue

        return response, str(response.url)

    raise ArticleFetchError("too many redirects")


def _strip_leading_title(text: str, title: str | None) -> str:
    """Drop the page headline when it repeats the feed item's title."""

    if not text or not title:
        return text

    lines = text.split("\n")
    for index, line in enumerate(lines):
        candidate = " ".join(line.split())
        if not candidate:
            continue
        if titles_match(candidate, title):
            del lines[index]
            return "\n".join(lines).strip()
        break
    return text


def _strip_leading_heading(value: str | None, title: str | None) -> str | None:
    """Drop a leading extracted heading that repeats the item title."""

    if not value or not title:
        return value

    soup = BeautifulSoup(value, "html.parser")
    for node in soup.contents:
        if isinstance(node, NavigableString):
            if str(node).strip():
                return value
            continue
        if not isinstance(node, Tag):
            continue
        if node.name in {"h1", "h2", "h3", "h4", "h5", "h6", "p"}:
            if node.name == "p" and node.find("img") is not None:
                return value
            candidate = " ".join(node.get_text(" ", strip=True).split())
            if titles_match(candidate, title):
                node.decompose()
                cleaned = str(soup).strip()
                return cleaned or None
        return value
    return value


def _strip_metadata_lists(value: str | None) -> str | None:
    """Drop one-item lists that only repeat the page's byline labels."""

    if not value:
        return value

    soup = BeautifulSoup(value, "html.parser")
    removed = False
    for node in soup.find_all(["ul", "ol"]):
        items = node.find_all("li", recursive=False)
        if len(items) != 1:
            continue
        label = " ".join(items[0].get_text(" ", strip=True).split())
        if _METADATA_LABEL.fullmatch(label):
            node.decompose()
            removed = True

    if not removed:
        return value
    cleaned = str(soup).strip()
    return cleaned or None


def _extract_page_metadata(body: bytes, url: str) -> PageMetadata:
    """Read writer and cover information from the page's structured metadata.

    Using the page metadata instead of scraping arbitrary text keeps promo
    blocks, navigation labels and newsletter sign-ups out of the frontmatter.
    """

    try:
        tree = trafilatura.load_html(body)
        if tree is None:
            return PageMetadata()
        metadata = trafilatura.extract_metadata(tree, default_url=url, extensive=True)
    except Exception:  # pragma: no cover - malformed metadata is not fatal
        logger.debug("Article metadata extraction failed", exc_info=True)
        return PageMetadata()

    if metadata is None:
        return PageMetadata()

    image = safe_image_url(getattr(metadata, "image", None), base_url=url)
    if image and is_promo_image(image):
        image = None

    return PageMetadata(
        author=clean_byline(getattr(metadata, "author", None)),
        cover_image=image,
        cover_image_alt=clean_meta_text(getattr(metadata, "image_alt", None)),
    )


def _choose_cover(
    html: str | None,
    metadata: PageMetadata,
) -> tuple[str | None, str | None, str | None]:
    """Prefer the actual lead image, then fall back to the page's cover tag."""

    leading = leading_image(html)
    if leading is not None:
        return leading

    if metadata.cover_image:
        alt = image_alt_for(html, metadata.cover_image) or metadata.cover_image_alt
        return metadata.cover_image, alt, None
    return None, None, None


def _store(session: Session, item: Item, result: ArticleResult) -> ArticleResult:
    item.fetch_status = result.status
    item.content_fetched_at = utcnow()
    if result.status == "ok" and result.text:
        item.content_full = result.text
        # Prefer the extracted article markup so headings, lists, quotes and
        # images survive. A page with no usable markup clears the feed fragment
        # so the reader renders the full plain text instead of a summary.
        item.content_html = result.html
        if result.author:
            item.author = result.author
        if result.cover_image:
            changed = result.cover_image != item.cover_image
            item.cover_image = result.cover_image
            if changed or result.cover_image_alt:
                item.cover_image_alt = result.cover_image_alt
            if changed or result.cover_caption:
                item.cover_caption = result.cover_caption
    session.flush()
    return result


def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    buffer = bytearray()
    truncated = False

    for chunk in response.iter_bytes():
        remaining = max_bytes - len(buffer)
        if remaining <= 0:
            truncated = True
            break
        buffer.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
            break

    return bytes(buffer), truncated


def _is_html(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    if not content_type:
        return True
    return any(
        marker in content_type
        for marker in ("text/html", "application/xhtml", "text/plain", "application/xml")
    )


def _raise_for_status(response: httpx.Response) -> None:
    response.raise_for_status()


def _status_for_http(status_code: int) -> FetchStatus:
    if status_code in {401, 402, 403, 451}:
        return "blocked"
    return "error"


def _domain_lock(host: str) -> threading.Lock:
    with _DOMAIN_REGISTRY_LOCK:
        return _DOMAIN_LOCKS.setdefault(host, threading.Lock())


def _wait_for_domain(host: str, delay: float) -> None:
    if delay <= 0:
        return
    elapsed = time.monotonic() - _DOMAIN_LAST.get(host, 0.0)
    if elapsed < delay:
        time.sleep(delay - elapsed)


def _capture_error(exc: Exception, *, host: str, status: FetchStatus) -> None:
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("article.host", host)
            scope.set_tag("article.status", status)
            sentry_sdk.capture_exception(ArticleFetchError(f"{type(exc).__name__}: {status}"))
    except Exception:  # pragma: no cover - telemetry must never break extraction
        logger.debug("Sentry article capture failed", exc_info=True)


def _record_metrics(result: ArticleResult, elapsed_ms: float) -> None:
    try:
        sentry_sdk.metrics.count(
            "article.fetch",
            1,
            attributes={"status": result.status},
        )
        sentry_sdk.metrics.distribution(
            "article.fetch.duration",
            elapsed_ms,
            unit="millisecond",
            attributes={"status": result.status},
        )
        if result.text:
            sentry_sdk.metrics.distribution(
                "article.chars",
                len(result.text),
                attributes={"status": result.status},
            )
    except Exception:  # pragma: no cover - telemetry must never break extraction
        logger.debug("Sentry article metrics failed", exc_info=True)
