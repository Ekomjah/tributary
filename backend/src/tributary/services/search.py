from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import sentry_sdk
import serpapi
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..db import utcnow
from ..models import Feed, Item, SearchCache
from ..schemas import ItemOut
from . import feeds

logger = logging.getLogger(__name__)

__all__ = [
    "SearchBackend",
    "SearchError",
    "SearchOutcome",
    "SearchParams",
    "make_backend",
    "make_params",
    "normalize_results",
    "run_search",
]

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FRESHNESS = {"day": "d", "week": "w", "month": "m", "year": "y"}


class SearchError(RuntimeError):
    """A search could not run, with a message safe to show the user."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class SearchBackend(Protocol):
    def search(
        self,
        *,
        engine: str,
        q: str,
        num: int,
        hl: str,
        gl: str,
        tbs: str | None,
    ) -> dict[str, Any]:
        """Return the raw SerpAPI payload."""


class SerpApiBackend:
    def __init__(self, api_key: str, timeout: float) -> None:
        self._client = serpapi.Client(api_key=api_key, timeout=timeout)

    def search(
        self,
        *,
        engine: str,
        q: str,
        num: int,
        hl: str,
        gl: str,
        tbs: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": engine,
            "q": q,
            "num": num,
            "hl": hl,
            "gl": gl,
        }
        if tbs:
            params["tbs"] = tbs
        return self._client.search(params).as_dict()


@dataclass(slots=True)
class SearchParams:
    q: str
    engine: str = "google_news"
    gl: str = "us"
    hl: str = "en"
    freshness: str | None = None
    max_results: int = 10

    def canonical(self) -> dict[str, Any]:
        return {
            "q": self.q,
            "engine": self.engine,
            "gl": self.gl,
            "hl": self.hl,
            "freshness": self.freshness,
            "max_results": self.max_results,
        }

    @property
    def cache_key(self) -> str:
        payload = json.dumps(self.canonical(), sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def tbs(self) -> str | None:
        if self.freshness is None:
            return None
        return f"qdr:{_FRESHNESS[self.freshness]}"


@dataclass(slots=True)
class SearchOutcome:
    query: str
    params: SearchParams
    items: list[ItemOut]
    cached: bool
    seconds: float


def make_params(
    settings: Settings,
    query: str,
    *,
    engine: str | None = None,
    gl: str | None = None,
    hl: str | None = None,
    freshness: str | None = None,
    max_results: int | None = None,
) -> SearchParams:
    cleaned = _CONTROL.sub(" ", query).strip()[:500]
    if not cleaned:
        raise SearchError("The search query is empty.")
    return SearchParams(
        q=cleaned,
        engine=engine or settings.serpapi_engine,
        gl=(gl or "us").strip().lower(),
        hl=(hl or "en").strip().lower(),
        freshness=freshness,
        max_results=min(max_results or settings.serpapi_max_results, 20),
    )


def make_backend(
    settings: Settings,
    backend: SearchBackend | None = None,
) -> SearchBackend:
    if backend is not None:
        return backend
    if not settings.serpapi_api_key:
        raise SearchError(
            "SERPAPI_API_KEY is not set. Add it to .env to enable web search.",
            status_code=503,
        )
    return SerpApiBackend(settings.serpapi_api_key, settings.serpapi_timeout)


def run_search(
    session: Session,
    settings: Settings,
    params: SearchParams,
    *,
    backend: SearchBackend | None = None,
    persist: bool = True,
    raw_query: str | None = None,
) -> SearchOutcome:
    """Search SerpAPI, cache the normalized results, and store virtual items."""

    started = time.perf_counter()
    cached = False
    row = session.get(SearchCache, params.cache_key)

    if row is not None and row.expires_at > utcnow():
        results = list(row.results_json)[: params.max_results]
        cached = True
        _metric_count("search.cache_hits", {"engine": params.engine})
    else:
        active_backend = make_backend(settings, backend)
        payload = _call_backend(active_backend, params, started)
        # google_news ignores `num`, so enforce the requested cap ourselves.
        results = normalize_results(payload, params.engine)[: params.max_results]
        _store_cache(session, params, results, settings.serpapi_cache_ttl)
        _metric_count(
            "search.requests",
            {"engine": params.engine, "status": "ok"},
        )
        _metric_distribution("search.results", len(results), {"engine": params.engine})

    if persist:
        items = _persist(session, params, results, raw_query=raw_query)
    else:
        items = [
            ItemOut(
                id=index,
                feed_id=0,
                guid=str(result["guid"]),
                title=str(result["title"]),
                link=str(result["link"]),
                published=_parse_date(result.get("published")),
                content=str(result.get("snippet") or ""),
                source=str(result.get("source") or "") or None,
                is_read=False,
                starred=False,
                fetched_at=utcnow(),
                labels=[],
            )
            for index, result in enumerate(results, start=1)
        ]

    elapsed = time.perf_counter() - started
    _metric_distribution("search.duration", elapsed * 1000, {"engine": params.engine})
    return SearchOutcome(
        query=raw_query or params.q,
        params=params,
        items=items,
        cached=cached,
        seconds=elapsed,
    )


def _call_backend(
    backend: SearchBackend,
    params: SearchParams,
    started: float,
) -> dict[str, Any]:
    with sentry_sdk.start_span(op="search.serpapi", name=params.engine) as span:
        span.set_data("search.engine", params.engine)
        span.set_data("search.num", params.max_results)
        span.set_data("search.freshness", params.freshness)
        try:
            payload = backend.search(
                engine=params.engine,
                q=params.q,
                num=params.max_results,
                hl=params.hl,
                gl=params.gl,
                tbs=params.tbs,
            )
        except Exception as exc:
            span.set_status("internal_error")
            _metric_count(
                "search.errors",
                {
                    "engine": params.engine,
                    "error": type(exc).__name__,
                },
            )
            raise SearchError(_safe_error(exc), status_code=_error_status(exc)) from exc

        span.set_data("search.duration_ms", round((time.perf_counter() - started) * 1000, 1))
        return payload


def _error_status(exc: Exception) -> int:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return 429
    return 502


def _safe_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status in {401, 403}:
        return "SerpAPI rejected the request. Check SERPAPI_API_KEY."
    if status == 429:
        return "SerpAPI rate limit or quota exceeded. Try again later."
    if isinstance(status, int) and status > 0:
        return f"SerpAPI returned HTTP {status}."
    return f"SerpAPI request failed ({type(exc).__name__})."


def normalize_results(payload: dict[str, Any], engine: str) -> list[dict[str, Any]]:
    """Turn news or organic results into the feed-item shape."""

    key = "news_results" if engine == "google_news" else "organic_results"
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        return []

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in _flatten_entries(raw):
        link = entry.get("link") or entry.get("url")
        if not isinstance(link, str) or not link.strip():
            continue
        canonical = feeds.normalize_url(link)
        if canonical in seen:
            continue
        seen.add(canonical)

        source = entry.get("source")
        if isinstance(source, dict):
            source = source.get("name")

        normalized.append(
            {
                "guid": canonical,
                "title": str(entry.get("title") or canonical)[:1000],
                "link": link,
                "snippet": str(
                    entry.get("snippet") or entry.get("description") or ""
                )[:20_000],
                "source": str(source or "")[:500],
                "published": entry.get("iso_date")
                or entry.get("date")
                or entry.get("published_at"),
            }
        )

    return normalized


def _flatten_entries(entries: list[Any]):
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stories = entry.get("stories")
        if isinstance(stories, list) and stories:
            for story in stories:
                if isinstance(story, dict):
                    yield story
            continue
        yield entry


def _persist(
    session: Session,
    params: SearchParams,
    results: list[dict[str, Any]],
    *,
    raw_query: str | None,
) -> list[ItemOut]:
    url = f"search://{params.cache_key}"
    feed = session.scalar(select(Feed).where(Feed.url == url))
    title = f"Search: {raw_query or params.q}"[:500]

    if feed is None:
        feed = Feed(url=url, title=title, kind="search")
        session.add(feed)
        session.flush()
    else:
        feed.kind = "search"
        feed.title = title

    existing = set(session.scalars(select(Item.guid).where(Item.feed_id == feed.id)).all())
    for result in results:
        guid = str(result["guid"])
        if guid in existing:
            continue
        session.add(
            Item(
                feed_id=feed.id,
                guid=guid,
                title=str(result["title"]),
                link=str(result["link"]),
                published=_parse_date(result.get("published")),
                content=str(result.get("snippet") or ""),
                source=str(result.get("source") or "") or None,
                fetched_at=utcnow(),
            )
        )
        existing.add(guid)

    session.flush()
    stored = session.scalars(
        select(Item)
        .options(selectinload(Item.labels))
        .where(Item.feed_id == feed.id)
        .order_by(
            Item.published.is_(None),
            Item.published.desc(),
            Item.fetched_at.desc(),
            Item.id.desc(),
        )
    ).all()
    return [ItemOut.model_validate(item) for item in stored]


def _store_cache(
    session: Session,
    params: SearchParams,
    results: list[dict[str, Any]],
    ttl: int,
) -> None:
    now = utcnow()
    expires = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)
    row = session.get(SearchCache, params.cache_key)
    if row is None:
        session.add(
            SearchCache(
                params_hash=params.cache_key,
                params_json=params.canonical(),
                results_json=results,
                created_at=now,
                expires_at=expires,
            )
        )
    else:
        row.params_json = params.canonical()
        row.results_json = results
        row.created_at = now
        row.expires_at = expires

    session.flush()
    session.execute(delete(SearchCache).where(SearchCache.expires_at < now))
    session.flush()


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _metric_count(name: str, attributes: dict[str, Any]) -> None:
    try:
        sentry_sdk.metrics.count(name, 1, attributes=attributes)
    except Exception:  # pragma: no cover - telemetry must never break search
        logger.debug("Sentry search metric failed", exc_info=True)


def _metric_distribution(
    name: str,
    value: float,
    attributes: dict[str, Any],
) -> None:
    try:
        sentry_sdk.metrics.distribution(
            name,
            value,
            unit="millisecond" if "duration" in name else None,
            attributes=attributes,
        )
    except Exception:  # pragma: no cover - telemetry must never break search
        logger.debug("Sentry search metric failed", exc_info=True)
