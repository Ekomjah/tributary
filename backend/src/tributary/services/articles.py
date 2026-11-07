from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from html import escape as html_escape
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import httpx
import sentry_sdk
import trafilatura
from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import end_transaction, utcnow
from ..models import Item
from ..schemas import FetchStatus
from .feeds import normalize_url
from .pagekind import PageKind, classify_page
from .text import (
    clean_byline,
    clean_meta_text,
    html_to_text,
    image_alt_for,
    is_promo_image,
    leading_image,
    normalize_text,
    prose_chars,
    safe_image_url,
    sanitize_html,
    strip_leading_image,
    strip_page_chrome,
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
_REDDIT_HOSTS = frozenset(
    {
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "np.reddit.com",
        "m.reddit.com",
    }
)
_REDDIT_THREAD = re.compile(r"^/(?:r/[^/]+/)?comments/[a-z0-9]+(?:/|$)", re.IGNORECASE)
_REDDIT_RSS_LINK = re.compile(r"^\[?link\]?$", re.IGNORECASE)
_METADATA_LABEL = re.compile(
    r"^(?:published|updated|last updated|posted)"
    r"(?:\s*(?:on\s+)?[:,-]?\s*(?:\d.*|today.*|yesterday.*|just now.*))?$"
    r"|^(?:share|save|comments)(?:\s*\(\d+\))?$",
    re.IGNORECASE,
)

# A candidate below this many characters is never worth showing. It is lower
# than the configured article floor so short, genuinely real notes can still be
# accepted when the page declares itself an article.
_CANDIDATE_FLOOR = 80

# Containers ordered from most specific to broadest. The first selector that
# yields real prose wins, but an empty or near-empty match never stops the
# search, because many templates have an <article> wrapper around the hero only.
_CONTAINER_SELECTORS = (
    "[itemprop=articleBody]",
    "[itemprop=text]",
    "[data-testid=readme]",
    "#readme",
    ".markdown-body",
    ".md-content",
    ".theme-doc-markdown",
    ".doc-content",
    "[class*=article-body]",
    "[class*=article__body]",
    "[class*=article-content]",
    "[class*=entry-content]",
    "[class*=post-content]",
    "[class*=post-body]",
    "[class*=story-body]",
    "[class*=story-content]",
    "[class*=prose]",
    "article",
    "main",
    "[role=main]",
)

_ARTICLE_TYPES = frozenset(
    {
        "AnalysisNewsArticle",
        "Article",
        "BackgroundNewsArticle",
        "BlogPosting",
        "NewsArticle",
        "OpinionNewsArticle",
        "Report",
        "ReviewNewsArticle",
        "ScholarlyArticle",
        "TechArticle",
    }
)

_STATE_SCRIPT_IDS = frozenset(
    {
        "__apollo_state__",
        "__initial_state__",
        "__next_data__",
        "__nuxt_data__",
        "__remixcontext",
    }
)
_STATE_KEY = re.compile(
    r"(?:^|_)(?:article|body|content|description|html|markdown|text)$",
    re.IGNORECASE,
)
_STATE_SKIP_KEY = re.compile(
    r"(?:author|css|date|hash|icon|id|image|key|lang|locale|name|path|script|"
    r"slug|title|token|type|url)$",
    re.IGNORECASE,
)
_STATE_MAX_DEPTH = 12

# Short lines that only exist to sell, navigate or share. Long paragraphs are
# never treated as boilerplate just because they contain one of these words.
_BOILERPLATE_LINE = re.compile(
    r"^(?:about(?: us)?|advertisement|all rights reserved|contact(?: us)?|"
    r"cookie(?:s| policy)?|home|log in|menu|privacy(?: policy)?|read more|"
    r"related(?: articles| posts| stories)?|share(?: this)?|sign (?:in|up)|"
    r"sponsored|subscribe(?: to .*)?|terms(?: of (?:service|use))?)$",
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
    reason: str | None = None


@dataclass(slots=True)
class PageMetadata:
    """Structured frontmatter read from a page's own metadata tags."""

    author: str | None = None
    cover_image: str | None = None
    cover_image_alt: str | None = None


@dataclass(slots=True)
class _Candidate:
    """One possible representation of a page's article body."""

    text: str
    html: str | None
    reason: str
    prior: float = 1.0


@dataclass(slots=True)
class _ScoredCandidate:
    """A candidate plus the quality signals used to rank it."""

    candidate: _Candidate
    chars: int
    score: float


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
            reason="cached",
        )

    if not force and item.content_full:
        text = item.content_full.strip()
        item.content_full = text
        item.fetch_status = "ok"
        if item.content_fetched_at is None:
            item.content_fetched_at = utcnow()
        session.flush()
        return ArticleResult(status="ok", text=text, fetched=False, reason="content_full")

    if not item.link:
        return _store(
            session,
            item,
            ArticleResult(status="empty", error="no link", reason="no_link"),
        )

    # A long feed body is already the article for some publishers. Promoting it
    # is opt-in because many feeds use a long description as a teaser.
    if (
        not force
        and settings.article_trust_long_description
        and item.content.strip()
        and len(item.content.strip()) >= settings.article_min_chars
    ):
        text = item.content.strip()
        item.content_full = text
        item.fetch_status = "ok"
        if item.content_fetched_at is None:
            item.content_fetched_at = utcnow()
        session.flush()
        return ArticleResult(status="ok", text=text, fetched=False, reason="feed_fallback")

    host = urlsplit(item.link).hostname or "unknown"
    started = time.perf_counter()

    # Release the transaction opened by the item lookup before the page fetch.
    end_transaction(session)

    with sentry_sdk.start_span(op="article.fetch", name=host) as span:
        span.set_data("article.host", host)
        result = _fetch_page(
            item.link,
            host=host,
            title=item.title,
            settings=settings,
            client=client,
        )
        if (
            result.status == "empty"
            and settings.article_trust_long_description
            and item.content.strip()
            and len(item.content.strip()) >= settings.article_min_chars
        ):
            result = ArticleResult(
                status="ok",
                text=item.content.strip(),
                fetched=True,
                truncated=result.truncated,
                bytes_read=result.bytes_read,
                reason="feed_fallback",
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        span.set_data("article.status", result.status)
        span.set_data("article.reason", result.reason or "unknown")
        span.set_data("article.bytes", result.bytes_read)
        span.set_data("article.chars", len(result.text or ""))
        span.set_data("article.html_chars", len(result.html or ""))
        span.set_data("article.truncated", result.truncated)
        span.set_data("article.duration_ms", round(elapsed_ms, 1))
        if result.status == "error":
            span.set_status("internal_error")
        _record_metrics(result, elapsed_ms)
        logger.info(
            "article fetch host=%s status=%s reason=%s bytes=%d chars=%d "
            "html_chars=%d truncated=%s duration_ms=%.1f",
            host,
            result.status,
            result.reason or "unknown",
            result.bytes_read,
            len(result.text or ""),
            len(result.html or ""),
            result.truncated,
            elapsed_ms,
        )

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

    # The select above opened a transaction; do not hold it across every page
    # fetch in the backfill.
    end_transaction(session)

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
            if caption:
                # The stored fragment's caption belongs to the same image and
                # is more specific than a caption re-read from the page.
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
    allow_reddit: bool = True,
) -> ArticleResult:
    owns_client = client is None
    active_client = client or make_client(settings)
    response: httpx.Response | None = None

    try:
        try:
            response, final_url = _open_page(active_client, url, settings)
            _raise_for_status(response)
            if _is_pdf(response, final_url):
                return ArticleResult(status="empty", reason="pdf")
            if not _is_html(response):
                return ArticleResult(status="empty", error="not html", reason="not_html")

            body, truncated = _read_capped(response, settings.article_max_bytes)
            if not body:
                return ArticleResult(
                    status="empty",
                    error="empty response",
                    reason="empty_response",
                )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            status = _status_for_http(status_code)
            body = _read_error_body(exc.response, settings.article_max_bytes)
            reason = _http_reason(
                status_code,
                body,
                settings.article_min_chars,
            )
            if reason in {"js_challenge", "login_required", "paywall"}:
                status = "blocked"
            if reason == "js_challenge" and allow_reddit and _is_reddit_thread(url):
                recovered = _recover_reddit(
                    url,
                    title=title,
                    settings=settings,
                    client=active_client,
                )
                if recovered is not None:
                    return recovered
            _capture_error(exc, host=host, status=status)
            return ArticleResult(
                status=status,
                error=f"HTTP {status_code}",
                reason=reason,
            )
        except UnsafeUrlError as exc:
            _capture_error(exc, host=host, status="error")
            return ArticleResult(status="error", error="unsafe url", reason="unsafe_url")
        except ArticleFetchError as exc:
            _capture_error(exc, host=host, status="error")
            message = str(exc)
            reason = "timeout" if "timed out" in message.lower() else "fetch_error"
            return ArticleResult(status="error", error=message, reason=reason)
        except httpx.TimeoutException as exc:
            _capture_error(exc, host=host, status="error")
            return ArticleResult(status="error", error=type(exc).__name__, reason="timeout")
        except httpx.HTTPError as exc:
            _capture_error(exc, host=host, status="error")
            return ArticleResult(
                status="error",
                error=type(exc).__name__,
                reason="network_error",
            )
        finally:
            if response is not None:
                response.close()

        # A challenge page carries no article. Detect it before trafilatura
        # runs, both to classify it correctly and to keep its noise out of the
        # extraction log.
        early = classify_page(body, status_code=response.status_code)
        if early.kind is PageKind.JS_CHALLENGE:
            if allow_reddit and _is_reddit_thread(url):
                recovered = _recover_reddit(
                    url,
                    title=title,
                    settings=settings,
                    client=active_client,
                )
                if recovered is not None:
                    return recovered
            return ArticleResult(
                status="blocked",
                truncated=truncated,
                bytes_read=len(body),
                reason="js_challenge",
            )

        try:
            candidates = _collect_candidates(body, final_url)
        except Exception as exc:  # pragma: no cover - malformed page
            _capture_error(exc, host=host, status="error")
            return ArticleResult(
                status="error",
                truncated=truncated,
                bytes_read=len(body),
                error=type(exc).__name__,
                reason="extract_error",
            )

        metadata = _extract_page_metadata(body, final_url)
        scored = _score_candidates(candidates)
        content = [item for item in scored if item.candidate.reason != "meta_description"]
        best_chars = max((item.chars for item in content), default=0)
        chosen = None
        if best_chars >= settings.article_min_chars:
            chosen = _choose_candidate(content, settings=settings)

        if chosen is None:
            classification = classify_page(
                body,
                status_code=response.status_code,
                extracted_chars=best_chars,
                min_chars=settings.article_min_chars,
            )
            if classification.kind is PageKind.JS_CHALLENGE:
                if allow_reddit and _is_reddit_thread(url):
                    recovered = _recover_reddit(
                        url,
                        title=title,
                        settings=settings,
                        client=active_client,
                    )
                    if recovered is not None:
                        return recovered
                return ArticleResult(
                    status="blocked",
                    truncated=truncated,
                    bytes_read=len(body),
                    reason="js_challenge",
                )
            if classification.kind is PageKind.LOGIN_REQUIRED:
                return ArticleResult(
                    status="blocked",
                    truncated=truncated,
                    bytes_read=len(body),
                    reason="login_required",
                )
            if classification.kind is PageKind.PAYWALL:
                return ArticleResult(
                    status="blocked",
                    truncated=truncated,
                    bytes_read=len(body),
                    reason="paywall",
                )

            if _page_article_signals(body):
                chosen = _choose_short_candidate(content, settings=settings)
            if chosen is None:
                descriptions = [
                    item for item in scored if item.candidate.reason == "meta_description"
                ]
                chosen = _choose_candidate(descriptions, settings=settings)
            if chosen is None:
                return ArticleResult(
                    status="empty",
                    text=None,
                    truncated=truncated,
                    bytes_read=len(body),
                    reason="too_short",
                )

        html = None
        if chosen.candidate.html:
            html = _strip_leading_heading(
                sanitize_html(chosen.candidate.html, base_url=final_url),
                title,
            )
            html = _strip_metadata_lists(html)
        text = normalize_text(
            html_to_text(html) if html else _strip_leading_title(chosen.candidate.text, title)
        ).strip()
        if not text:
            return ArticleResult(
                status="empty",
                text=None,
                truncated=truncated,
                bytes_read=len(body),
                reason="too_short",
            )

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
            reason=chosen.candidate.reason,
        )
    finally:
        if owns_client:
            active_client.close()


def _collect_candidates(body: bytes, url: str) -> list[_Candidate]:
    """Run every extraction strategy and return their distinct proposals.

    The trafilatura calls stay first and unchanged in spirit: precision is the
    incumbent, recall is a second opinion. Structured data, embedded
    application state, semantic containers and a chrome-stripped page rescue
    cover the shapes trafilatura cannot see. One failing producer never sinks
    the others.
    """

    candidates: list[_Candidate] = []
    for recall in (False, True):
        try:
            candidate = _candidate_trafilatura(body, url, recall=recall)
        except Exception:  # pragma: no cover - malformed page
            logger.debug("trafilatura candidate failed", exc_info=True)
            continue
        if candidate is not None:
            candidates.append(candidate)

    producers = (
        _candidate_structured,
        _candidate_embedded_state,
        _candidate_containers,
        _candidate_page_rescue,
        _candidate_meta,
    )
    for producer in producers:
        try:
            candidate = producer(body, url)
        except Exception:  # pragma: no cover - one producer must not sink the rest
            logger.debug("Article candidate %s failed", producer.__name__, exc_info=True)
            continue
        if candidate is not None:
            candidates.append(candidate)

    return _dedupe_candidates(candidates)


def _dedupe_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    """Keep the strongest candidate for each distinct body text."""

    unique: dict[str, _Candidate] = {}
    for candidate in candidates:
        key = " ".join(candidate.text.split())
        if not key:
            continue
        current = unique.get(key)
        if current is None or candidate.prior > current.prior:
            unique[key] = candidate
    return list(unique.values())


def _candidate_trafilatura(
    body: bytes,
    url: str,
    *,
    recall: bool,
) -> _Candidate | None:
    """Return trafilatura's HTML output and derive plain text from it.

    Deriving text from the same markup the reader will render keeps the two
    representations aligned, so a table or code block cannot survive in one and
    vanish from the other.
    """

    html = trafilatura.extract(
        body,
        url=url,
        output_format="html",
        include_links=True,
        include_comments=False,
        include_tables=True,
        include_images=True,
        include_formatting=True,
        favor_precision=not recall,
        favor_recall=recall,
    )
    reason = "extracted_recall" if recall else "extracted"
    prior = 0.97 if recall else 1.0
    if html:
        text = html_to_text(html)
        if text.strip():
            return _Candidate(text=text, html=html, reason=reason, prior=prior)

    text = trafilatura.extract(
        body,
        url=url,
        include_links=False,
        include_comments=False,
        include_tables=True,
        favor_precision=not recall,
        favor_recall=recall,
    )
    if not text or not text.strip():
        return None
    return _Candidate(text=text, html=None, reason=reason, prior=prior)


def _candidate_structured(body: bytes, url: str) -> _Candidate | None:
    structured = _structured_data(body, url)
    if structured is None:
        return None
    text, html = structured
    return _Candidate(text=text, html=html, reason="structured_data", prior=1.02)


def _candidate_meta(body: bytes, url: str) -> _Candidate | None:
    description = _meta_description(body, url)
    if not description:
        return None
    return _Candidate(text=description, html=None, reason="meta_description", prior=0.65)


def _candidate_containers(body: bytes, url: str) -> _Candidate | None:
    """Harvest the first semantic container that actually yields prose."""

    soup = BeautifulSoup(body, "html.parser")
    best_html: str | None = None
    best_chars = 0
    for selector in _CONTAINER_SELECTORS:
        for node in soup.select(selector):
            fragment = BeautifulSoup(str(node), "html.parser")
            strip_page_chrome(fragment, comments=False)
            chars = prose_chars(fragment)
            if chars > best_chars:
                best_chars = chars
                best_html = str(fragment)
        if best_chars >= _CANDIDATE_FLOOR:
            break

    if best_html is None:
        return None
    text = html_to_text(best_html)
    if not text.strip():
        return None
    return _Candidate(text=text, html=best_html, reason="container", prior=0.95)


def _candidate_page_rescue(body: bytes, url: str) -> _Candidate | None:
    """Read the whole page after removing its chrome, as a last resort."""

    soup = BeautifulSoup(body, "html.parser")
    strip_page_chrome(soup, comments=True)
    html = str(soup)
    text = html_to_text(html)
    if len(text.strip()) < _CANDIDATE_FLOOR:
        return None
    return _Candidate(text=text, html=html, reason="page_rescue", prior=0.92)


def _candidate_embedded_state(body: bytes, url: str) -> _Candidate | None:
    """Read article text stored in a framework's JSON bootstrap state."""

    soup = BeautifulSoup(body, "html.parser")
    best = ""
    for script in soup.find_all("script"):
        content_type = str(script.get("type") or "").lower()
        script_id = str(script.get("id") or "").lower()
        if "ld+json" in content_type:
            continue
        if "json" not in content_type and script_id not in _STATE_SCRIPT_IDS:
            continue
        raw = script.string if script.string is not None else script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for value in _state_strings(payload):
            if len(value) > len(best) and _looks_like_prose(value):
                best = value

    if not best:
        return None

    if "<" in best:
        fragment = BeautifulSoup(best, "html.parser")
        strip_page_chrome(fragment, comments=False)
        html = str(fragment)
        text = html_to_text(html)
    else:
        text = best.strip()
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
        html = "".join(f"<p>{html_escape(part)}</p>" for part in paragraphs)
    if not text.strip():
        return None
    return _Candidate(text=text, html=html or None, reason="embedded_state", prior=0.93)


def _state_strings(value: object, *, depth: int = 0):
    """Yield long strings held under body-like keys in a JSON state tree."""

    if depth > _STATE_MAX_DEPTH:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)).lower()
            if isinstance(child, str):
                if (
                    len(child) >= 200
                    and _STATE_KEY.search(key_text)
                    and not _STATE_SKIP_KEY.search(key_text)
                ):
                    yield child
            elif isinstance(child, (dict, list)):
                yield from _state_strings(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                yield from _state_strings(child, depth=depth + 1)


def _looks_like_prose(value: str) -> bool:
    text = value.strip()
    if len(text) < 200:
        return False
    if text.startswith(("{", "[", "data:image")):
        return False
    if "<p" in text or "<br" in text or "</" in text or "\n\n" in text:
        return True
    words = text.split()
    if len(words) < 40:
        return False
    spaces = sum(1 for char in text if char.isspace())
    return spaces / len(text) >= 0.08


def _page_article_signals(body: bytes) -> bool:
    """Return whether the page declares itself to be an article."""

    soup = BeautifulSoup(body, "html.parser")
    for attrs in ({"property": "og:type"}, {"name": "og:type"}):
        tag = soup.find("meta", attrs=attrs)
        if tag is not None and "article" in str(tag.get("content") or "").lower():
            return True
    if soup.find("meta", attrs={"property": "article:published_time"}) is not None:
        return True

    for script in soup.find_all("script"):
        if "ld+json" not in str(script.get("type") or "").lower():
            continue
        raw = script.string if script.string is not None else script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for node in _json_nodes(payload):
            value = node.get("@type")
            types = value if isinstance(value, list) else [value]
            if any(str(item) in _ARTICLE_TYPES for item in types):
                return True

    article = soup.find("article")
    return (
        article is not None
        and len(" ".join(article.get_text(" ", strip=True).split())) >= _CANDIDATE_FLOOR
    )


def _score_candidate(candidate: _Candidate) -> _ScoredCandidate | None:
    """Score a candidate by volume, link density and repeated chrome."""

    text = normalize_text(candidate.text).strip()
    if not text:
        return None

    link_density = 0.0
    if candidate.html:
        soup = BeautifulSoup(candidate.html, "html.parser")
        total = len(" ".join(soup.get_text(" ", strip=True).split()))
        linked = len(
            " ".join(
                " ".join(link.get_text(" ", strip=True).split()) for link in soup.find_all("a")
            )
        )
        link_density = linked / total if total else 0.0

    lines = [" ".join(line.split()) for line in text.split("\n") if line.strip()]
    duplicate_ratio = 0.0
    boilerplate_ratio = 0.0
    if lines:
        duplicate_ratio = 1 - (len(set(lines)) / len(lines))
        boilerplate_ratio = sum(
            1 for line in lines if len(line) <= 80 and _BOILERPLATE_LINE.fullmatch(line)
        ) / len(lines)

    score = len(text) * candidate.prior
    if link_density > 0.65:
        # A block that is mostly anchor text is navigation or a link list, not
        # an article body.
        return None
    if link_density > 0.4:
        score *= 0.6
    score *= 1 - min(duplicate_ratio, 0.6)
    score *= 1 - min(boilerplate_ratio, 0.4)
    return _ScoredCandidate(candidate=candidate, chars=len(text), score=score)


def _score_candidates(candidates: list[_Candidate]) -> list[_ScoredCandidate]:
    """Score every candidate and drop the ones too small to be content."""

    return [
        item
        for item in (_score_candidate(candidate) for candidate in candidates)
        if item is not None and item.chars >= _CANDIDATE_FLOOR
    ]


def _choose_candidate(
    scored: list[_ScoredCandidate],
    *,
    settings: Settings,
) -> _ScoredCandidate | None:
    """Pick the best candidate that clears the normal article floor."""

    passing = [item for item in scored if item.chars >= settings.article_min_chars]
    if not passing:
        return None
    return max(passing, key=lambda item: item.score)


def _choose_short_candidate(
    scored: list[_ScoredCandidate],
    *,
    settings: Settings,
) -> _ScoredCandidate | None:
    """Pick a short candidate for a page that explicitly declares an article."""

    floor = max(
        _CANDIDATE_FLOOR,
        min(settings.article_short_article_floor, settings.article_min_chars),
    )
    short = [item for item in scored if item.chars >= floor]
    if not short:
        return None
    return max(short, key=lambda item: item.score)


def _is_pdf(response: httpx.Response, final_url: str) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return "application/pdf" in content_type or urlsplit(final_url).path.lower().endswith(".pdf")


def _read_error_body(response: httpx.Response, max_bytes: int) -> bytes:
    """Read a small error response so a challenge page can still be classified."""

    if response.is_stream_consumed:
        return b""
    try:
        body, _truncated = _read_capped(response, min(max_bytes, 128_000))
        return body
    except Exception:  # pragma: no cover - an unreadable error body is not fatal
        return b""


def _http_reason(status_code: int, body: bytes, min_chars: int) -> str:
    if body:
        classification = classify_page(
            body,
            status_code=status_code,
            extracted_chars=0,
            min_chars=min_chars,
        )
        if classification.kind is PageKind.JS_CHALLENGE:
            return "js_challenge"
        if classification.kind is PageKind.LOGIN_REQUIRED:
            return "login_required"
        if classification.kind is PageKind.PAYWALL:
            return "paywall"
    return f"http_{status_code}"


def _json_nodes(value: object):
    """Yield every dictionary inside a parsed JSON-LD document."""

    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                yield from _json_nodes(child)


def _structured_data(body: bytes, url: str) -> tuple[str, str | None] | None:
    """Return the longest article body published in JSON-LD, when one is present."""

    soup = BeautifulSoup(body, "html.parser")
    best: tuple[str, str | None] | None = None
    for script in soup.find_all("script"):
        content_type = str(script.get("type") or "").lower()
        if "ld+json" not in content_type:
            continue
        raw = script.string if script.string is not None else script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue

        for node in _json_nodes(payload):
            for field in ("articleBody", "text"):
                candidate = node.get(field)
                if not isinstance(candidate, str) or not candidate.strip():
                    continue
                if "<" in candidate:
                    text = html_to_text(candidate).strip()
                    html = sanitize_html(candidate, base_url=url)
                else:
                    text = normalize_text(candidate).strip()
                    html = None
                if text and (best is None or len(text) > len(best[0])):
                    best = (text, html)
    return best


def _meta_description(body: bytes, url: str) -> str | None:
    """Return the longest useful page description, when the page has one."""

    soup = BeautifulSoup(body, "html.parser")
    best: str | None = None
    for attrs in (
        {"property": "og:description"},
        {"name": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag is None:
            continue
        value = str(tag.get("content") or "").strip()
        if not value:
            continue
        text = html_to_text(value).strip()
        if text and (best is None or len(text) > len(best)):
            best = text
    return best


def _is_reddit_thread(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return host in _REDDIT_HOSTS and bool(_REDDIT_THREAD.match(parts.path))


def _reddit_rss_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return urlunsplit(("https", "www.reddit.com", f"{path}/.rss", "", ""))


def _recover_reddit(
    url: str,
    *,
    title: str,
    settings: Settings,
    client: httpx.Client,
) -> ArticleResult | None:
    """Read a Reddit thread through its public Atom feed.

    Reddit serves a proof-of-work challenge to plain HTML clients. Its ``.rss``
    endpoint stays public, so use the thread entry for a self-post body and
    follow at most one external ``[link]`` to the real article.
    """

    response: httpx.Response | None = None
    try:
        try:
            response, _final_url = _open_page(client, _reddit_rss_url(url), settings)
            if response.status_code >= 400:
                return None
            body, _truncated = _read_capped(response, settings.article_max_bytes)
        finally:
            if response is not None:
                response.close()
    except (ArticleFetchError, UnsafeUrlError, httpx.HTTPError):
        return None

    if not body:
        return None

    parsed = feedparser.parse(body)
    entry = _reddit_post_entry(parsed.entries, url)
    if entry is None:
        return None

    raw = _entry_content_value(entry)
    external = _reddit_external_link(raw, url)
    if external:
        link_host = urlsplit(external).hostname or "unknown"
        result = _fetch_page(
            external,
            host=link_host,
            title=title,
            settings=settings,
            client=client,
            allow_reddit=False,
        )
        if result.status == "ok":
            result.reason = "reddit_link"
            return result
        self_post = _reddit_body_result(raw, url)
        return self_post or result

    return _reddit_body_result(raw, url)


def _reddit_post_entry(entries: list[object], url: str) -> object | None:
    target = normalize_url(url).rstrip("/")
    for entry in entries:
        if not hasattr(entry, "get"):
            continue
        entry_id = str(entry.get("id") or "")
        if entry_id.startswith("t3_"):
            return entry
        link = str(entry.get("link") or "")
        if link and normalize_url(link).rstrip("/") == target:
            return entry
    return entries[0] if entries else None


def _entry_content_value(entry: object) -> str:
    content = entry.get("content") if hasattr(entry, "get") else None
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("value"):
                return str(part["value"])
    elif isinstance(content, dict) and content.get("value"):
        return str(content["value"])
    if hasattr(entry, "get"):
        return str(entry.get("summary") or "")
    return ""


def _reddit_external_link(raw: str, base_url: str) -> str | None:
    soup = BeautifulSoup(raw, "html.parser")
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if not _REDDIT_RSS_LINK.match(label):
            continue
        href = urljoin(base_url, str(anchor.get("href") or "").strip())
        parts = urlsplit(href)
        host = (parts.hostname or "").lower()
        if parts.scheme.lower() not in {"http", "https"} or not host:
            continue
        if (
            host in _REDDIT_HOSTS
            or host.endswith(".reddit.com")
            or host in {"redd.it", "www.redd.it"}
        ):
            continue
        return href
    return None


def _reddit_body(raw: str, url: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(raw, "html.parser")

    # Link posts put the thumbnail, submitter and [link] / [comments] markers
    # in a table. That table is not article text.
    for table in soup.find_all("table"):
        if "submitted by" in table.get_text(" ", strip=True).lower():
            table.decompose()
    for anchor in soup.find_all("a"):
        if _REDDIT_RSS_LINK.match(" ".join(anchor.get_text(" ", strip=True).split())):
            anchor.decompose()

    cleaned = str(soup)
    text = html_to_text(cleaned).strip()
    html = sanitize_html(cleaned, base_url=url) if text else None
    if html:
        text = html_to_text(html).strip() or text
    return text, html


def _reddit_body_result(raw: str, url: str) -> ArticleResult | None:
    text, html = _reddit_body(raw, url)
    if not text:
        return None
    return ArticleResult(
        status="ok",
        text=text,
        html=html,
        fetched=True,
        bytes_read=len(raw.encode("utf-8")),
        reason="reddit_self",
    )


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
        lock = _domain_lock(hop_host)
        if not lock.acquire(timeout=settings.article_lock_timeout):
            raise ArticleFetchError("timed out waiting for another fetch of this host")
        try:
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
        finally:
            lock.release()

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
    attributes = {
        "status": result.status,
        "reason": result.reason or "unknown",
    }
    try:
        sentry_sdk.metrics.count(
            "article.fetch",
            1,
            attributes=attributes,
        )
        sentry_sdk.metrics.distribution(
            "article.fetch.duration",
            elapsed_ms,
            unit="millisecond",
            attributes=attributes,
        )
        if result.text:
            sentry_sdk.metrics.distribution(
                "article.chars",
                len(result.text),
                attributes=attributes,
            )
    except Exception:  # pragma: no cover - telemetry must never break extraction
        logger.debug("Sentry article metrics failed", exc_info=True)
