from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
import sentry_sdk
import trafilatura
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..models import Item
from ..schemas import FetchStatus
from .urls import UnsafeUrlError, validate_public_url

logger = logging.getLogger(__name__)

__all__ = [
    "ArticleFetchError",
    "ArticleResult",
    "fetch_article",
    "make_client",
]

_DOMAIN_LOCKS: dict[str, threading.Lock] = {}
_DOMAIN_LAST: dict[str, float] = {}
_DOMAIN_REGISTRY_LOCK = threading.Lock()

_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@dataclass(slots=True)
class ArticleResult:
    """Outcome of trying to obtain one item's full text."""

    status: FetchStatus
    text: str | None = None
    fetched: bool = False
    truncated: bool = False
    bytes_read: int = 0
    error: str | None = None


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
        result = _fetch_page(item.link, host=host, settings=settings, client=client)
        elapsed_ms = (time.perf_counter() - started) * 1000
        span.set_data("article.status", result.status)
        span.set_data("article.bytes", result.bytes_read)
        span.set_data("article.chars", len(result.text or ""))
        span.set_data("article.truncated", result.truncated)
        span.set_data("article.duration_ms", round(elapsed_ms, 1))
        if result.status == "error":
            span.set_status("internal_error")
        _record_metrics(result, elapsed_ms)

    return _store(session, item, result)


def _fetch_page(
    url: str,
    *,
    host: str,
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
        except Exception as exc:  # pragma: no cover - malformed page
            _capture_error(exc, host=host, status="error")
            return ArticleResult(
                status="error",
                truncated=truncated,
                bytes_read=len(body),
                error=type(exc).__name__,
            )

        text = (extracted or "").strip()
        if len(text) < settings.article_min_chars:
            return ArticleResult(
                status="empty",
                text=None,
                truncated=truncated,
                bytes_read=len(body),
            )

        return ArticleResult(
            status="ok",
            text=text,
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


def _store(session: Session, item: Item, result: ArticleResult) -> ArticleResult:
    item.fetch_status = result.status
    item.content_fetched_at = utcnow()
    if result.status == "ok" and result.text:
        item.content_full = result.text
        # The extracted article supersedes the feed's display fragment.
        item.content_html = None
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
