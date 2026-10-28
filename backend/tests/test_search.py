from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tributary.config import Settings
from tributary.db import utcnow
from tributary.models import Feed, Item, SearchCache
from tributary.services import feeds
from tributary.services import search as web_search

NEWS_PAYLOAD: dict[str, Any] = {
    "news_results": [
        {
            "title": "Regulators publish new AI rules",
            "link": "https://Example.com/ai-rules#top",
            "source": {"name": "Example News"},
            "iso_date": "2026-10-27T10:00:00Z",
            "snippet": "A short summary of the new rules.",
        },
        {
            "title": "Duplicate of the same story",
            "link": "https://example.com/ai-rules",
            "source": {"name": "Other News"},
            "snippet": "The same article through another link.",
        },
        {
            "title": "Missing a link",
            "snippet": "This result should be skipped.",
        },
        {
            "stories": [
                {
                    "title": "Nested story",
                    "link": "https://example.com/nested",
                    "source": {"name": "Nested News"},
                    "date": "2026-10-26",
                    "snippet": "A nested story.",
                }
            ]
        },
    ]
}


class FakeBackend:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.payload


class FakeHttpError(Exception):
    status_code = 429


def test_normalize_news_results_flattens_dedupes_and_skips_empty_links() -> None:
    results = web_search.normalize_results(NEWS_PAYLOAD, "google_news")

    assert [result["title"] for result in results] == [
        "Regulators publish new AI rules",
        "Nested story",
    ]
    assert results[0]["guid"] == "https://example.com/ai-rules"
    assert results[0]["source"] == "Example News"
    assert results[0]["snippet"] == "A short summary of the new rules."
    assert results[1]["published"] == "2026-10-26"


def test_normalize_web_results_uses_organic_results() -> None:
    payload = {
        "organic_results": [
            {
                "title": "Python packaging guide",
                "link": "https://example.com/python-packaging",
                "snippet": "How to package Python code.",
            },
            {"title": "No link"},
        ]
    }

    results = web_search.normalize_results(payload, "google")

    assert len(results) == 1
    assert results[0]["link"] == "https://example.com/python-packaging"
    assert results[0]["source"] == ""


def test_search_without_a_key_fails_with_an_actionable_message() -> None:
    settings = Settings(_env_file=None, serpapi_api_key=None)

    with pytest.raises(web_search.SearchError, match="SERPAPI_API_KEY") as info:
        web_search.make_backend(settings)

    assert info.value.status_code == 503


def test_run_search_persists_a_virtual_feed_and_items(
    db_session: Session,
    settings: Settings,
) -> None:
    backend = FakeBackend(NEWS_PAYLOAD)
    params = web_search.make_params(settings, "AI regulation", freshness="week")

    outcome = web_search.run_search(db_session, settings, params, backend=backend)
    db_session.commit()

    assert outcome.cached is False
    assert len(outcome.items) == 2
    assert outcome.items[0].source == "Example News"
    assert outcome.items[0].published is not None

    feed = db_session.scalar(select(Feed).where(Feed.kind == "search"))
    assert feed is not None
    assert feed.url.startswith("search://")
    assert feed.title == "Search: AI regulation"
    assert db_session.scalar(select(Item).where(Item.feed_id == feed.id)) is not None
    assert backend.calls[0]["tbs"] == "qdr:w"


def test_run_search_keeps_at_most_max_results(
    db_session: Session,
    settings: Settings,
) -> None:
    payload = {
        "news_results": [
            {"title": f"Story {index}", "link": f"https://example.com/{index}"}
            for index in range(3)
        ]
    }
    backend = FakeBackend(payload)
    params = web_search.make_params(settings, "AI regulation", max_results=2)

    outcome = web_search.run_search(db_session, settings, params, backend=backend)
    db_session.commit()

    assert len(outcome.items) == 2
    assert len(db_session.scalars(select(Item)).all()) == 2

    cached = web_search.run_search(db_session, settings, params, backend=backend)
    assert cached.cached is True
    assert len(cached.items) == 2


def test_run_search_is_served_from_the_cache_until_it_expires(
    db_session: Session,
    settings: Settings,
) -> None:
    backend = FakeBackend(NEWS_PAYLOAD)
    params = web_search.make_params(settings, "AI regulation")

    web_search.run_search(db_session, settings, params, backend=backend)
    db_session.commit()

    second = web_search.run_search(db_session, settings, params, backend=backend)
    assert second.cached is True
    assert len(backend.calls) == 1

    row = db_session.get(SearchCache, params.cache_key)
    assert row is not None
    row.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    third = web_search.run_search(db_session, settings, params, backend=backend)
    assert third.cached is False
    assert len(backend.calls) == 2


def test_run_search_maps_a_quota_error(
    db_session: Session,
    settings: Settings,
) -> None:
    backend = FakeBackend(error=FakeHttpError())
    params = web_search.make_params(settings, "AI regulation")

    with pytest.raises(web_search.SearchError) as info:
        web_search.run_search(db_session, settings, params, backend=backend)

    assert info.value.status_code == 429
    assert "quota" in str(info.value)


def test_run_search_with_no_results_still_creates_the_feed(
    db_session: Session,
    settings: Settings,
) -> None:
    backend = FakeBackend({})
    params = web_search.make_params(settings, "nothing matches")

    outcome = web_search.run_search(db_session, settings, params, backend=backend)
    db_session.commit()

    assert outcome.items == []
    feed = db_session.scalar(select(Feed).where(Feed.kind == "search"))
    assert feed is not None


def test_search_api_returns_items_and_hides_them_from_default_views(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend(NEWS_PAYLOAD)
    monkeypatch.setattr(
        web_search,
        "make_backend",
        lambda _settings, _backend=None: backend,
    )

    response = client.post(
        "/api/search",
        json={"query": "AI regulation", "freshness": "week"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["q"] == "AI regulation"
    assert body["engine"] == "google_news"
    assert body["freshness"] == "week"
    assert body["cached"] is False
    assert len(body["items"]) == 2
    feed_id = body["items"][0]["feed_id"]

    default_view = client.get("/api/items").json()
    assert default_view["total"] == 0

    search_view = client.get("/api/items", params={"feed_id": feed_id}).json()
    assert search_view["total"] == 2

    refresh = client.post(f"/api/feeds/{feed_id}/refresh")
    assert refresh.status_code == 400
    assert "Search feeds" in refresh.json()["detail"]


def test_search_api_reports_a_missing_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_key(settings: Settings, backend=None):
        raise web_search.SearchError(
            "SERPAPI_API_KEY is not set. Add it to .env to enable web search.",
            status_code=503,
        )
    monkeypatch.setattr(web_search, "make_backend", missing_key)

    response = client.post("/api/search", json={"query": "anything"})

    assert response.status_code == 503
    assert "SERPAPI_API_KEY" in response.json()["detail"]


def test_refresh_skips_search_feeds(
    session_factory: sessionmaker[Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session_factory() as session:
        session.add(Feed(url="search://abc", title="Search: x", kind="search"))
        session.add(Feed(url="https://example.com/feed.xml", title="Example"))
        session.commit()

    called: list[str] = []

    def fake_fetch(session, url, *, client, min_full_chars=500):
        called.append(url)
        return feeds.FetchResult(
            url=url,
            feed_id=1,
            title="Example",
            new_items=1,
            total_entries=1,
        )

    monkeypatch.setattr(feeds, "fetch_feed", fake_fetch)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))

    try:
        results = feeds.refresh_feeds(session_factory, settings, client=client)
    finally:
        client.close()

    assert called == ["https://example.com/feed.xml"]
    assert len(results) == 1
