from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tributary.models import Feed, Item, Label
from tributary.services import feeds

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>API Feed</title>
    <link>https://example.com/</link>
    <description>An API feed</description>
    <item>
      <title>API one</title>
      <link>https://example.com/posts/one</link>
      <guid>api-1</guid>
      <pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>
      <description>First body.</description>
    </item>
    <item>
      <title>API two</title>
      <link>https://example.com/posts/two</link>
      <guid>api-2</guid>
      <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
      <description>Second body.</description>
    </item>
  </channel>
</rss>
"""


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def seed_feed(
    db: Session,
    url: str = "https://example.com/feed.xml",
    title: str = "Example",
) -> Feed:
    feed = Feed(url=url, title=title)
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def seed_item(
    db: Session,
    feed: Feed,
    *,
    guid: str,
    title: str,
    content: str = "",
    is_read: bool = False,
    starred: bool = False,
    published: datetime | None = None,
    label: Label | None = None,
) -> Item:
    item = Item(
        feed_id=feed.id,
        guid=guid,
        title=title,
        link=f"https://example.com/posts/{guid}",
        content=content,
        is_read=is_read,
        starred=starred,
        published=published,
        fetched_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
    )
    if label is not None:
        item.labels.append(label)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def patch_feed_client(monkeypatch, handler) -> None:
    def make_client(settings):
        return mock_client(handler)

    monkeypatch.setattr(feeds, "make_client", make_client)


def test_feed_crud_and_validation(client: TestClient, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/rss+xml"},
            content=RSS.encode(),
        )

    patch_feed_client(monkeypatch, handler)

    created = client.post(
        "/api/feeds",
        json={"url": " HTTPS://Example.com/feed.xml#fragment ", "title": "Example"},
    )

    assert created.status_code == 201
    assert created.json()["feed"]["url"] == "https://example.com/feed.xml"
    assert created.json()["feed"]["title"] == "Example"
    assert created.json()["result"]["new_items"] == 2

    duplicate = client.post("/api/feeds", json={"url": "https://example.com/feed.xml"})
    assert duplicate.status_code == 409

    invalid = client.post("/api/feeds", json={"url": "not a url"})
    assert invalid.status_code == 422

    credentials = client.post(
        "/api/feeds",
        json={"url": "https://user:pass@example.com/feed.xml"},
    )
    assert credentials.status_code == 422

    feed_id = created.json()["feed"]["id"]
    assert client.get(f"/api/feeds/{feed_id}").status_code == 200
    assert len(client.get("/api/feeds").json()) == 1
    assert client.get("/api/items").json()["total"] == 2

    assert client.delete(f"/api/feeds/{feed_id}").status_code == 204
    assert client.get(f"/api/feeds/{feed_id}").status_code == 404
    assert client.get("/api/items").json()["total"] == 0


def test_create_rejects_non_feed_without_row(client: TestClient, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body>Not a feed</body></html>",
        )

    patch_feed_client(monkeypatch, handler)

    response = client.post("/api/feeds", json={"url": "https://example.com/blog"})

    assert response.status_code == 422
    assert client.get("/api/feeds").json() == []


def test_create_validates_and_ingests_in_one_request(client: TestClient, monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "application/rss+xml"},
            content=RSS.encode(),
        )

    patch_feed_client(monkeypatch, handler)

    response = client.post("/api/feeds", json={"url": "https://example.com/feed.xml"})

    assert response.status_code == 201
    assert calls == 1
    assert response.json()["feed"]["title"] == "API Feed"
    assert response.json()["result"]["new_items"] == 2
    assert client.get("/api/items").json()["total"] == 2


def test_create_maps_network_error_to_502(client: TestClient, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    patch_feed_client(monkeypatch, handler)

    response = client.post("/api/feeds", json={"url": "https://example.com/feed.xml"})

    assert response.status_code == 502
    assert client.get("/api/feeds").json() == []


def test_create_maps_unsafe_to_422(client: TestClient) -> None:
    response = client.post("/api/feeds", json={"url": "http://127.0.0.1/feed"})

    assert response.status_code == 422
    assert client.get("/api/feeds").json() == []


def test_discover_endpoint_returns_candidates(client: TestClient, monkeypatch) -> None:
    page = (
        b"<!doctype html><html><head><title>Example Blog</title>"
        b'<link rel="alternate" type="application/rss+xml" '
        b'title="Example Feed" href="/feed.xml"></head><body></body></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page,
        )

    patch_feed_client(monkeypatch, handler)

    response = client.post("/api/feeds/discover", json={"url": "example.com/blog"})

    assert response.status_code == 200
    body = response.json()
    assert body["input_url"] == "https://example.com/blog"
    assert body["page_title"] == "Example Blog"
    assert body["candidates"] == [
        {
            "url": "https://example.com/feed.xml",
            "title": "Example Feed",
            "kind": "rss",
        }
    ]


def test_discover_endpoint_maps_network_error_to_502(client: TestClient, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    patch_feed_client(monkeypatch, handler)

    response = client.post("/api/feeds/discover", json={"url": "https://example.com/blog"})

    assert response.status_code == 502


def test_refresh_feed_uses_the_feed_service(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    feed = seed_feed(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(handler))

    response = client.post(f"/api/feeds/{feed.id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["new_items"] == 2
    assert body["title"] == "API Feed"
    assert body["error"] is None

    items = client.get(f"/api/items?feed_id={feed.id}").json()
    assert items["total"] == 2


def test_refresh_all_isolates_a_dead_feed(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    good = seed_feed(db_session, "https://example.com/good.xml", "Good")
    bad = seed_feed(db_session, "https://example.com/bad.xml", "Bad")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("bad.xml"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, content=RSS.encode())

    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(handler))

    response = client.post("/api/feeds/refresh")

    assert response.status_code == 200
    results = {result["feed_id"]: result for result in response.json()}
    assert results[good.id]["new_items"] == 2
    assert results[bad.id]["error"] is not None


def test_item_filters_pagination_and_updates(client: TestClient, db_session: Session) -> None:
    feed = seed_feed(db_session)
    python = Label(name="python")
    db_session.add(python)
    db_session.commit()
    db_session.refresh(python)

    first = seed_item(
        db_session,
        feed,
        guid="python-release",
        title="Python release",
        content="FastAPI ships a new version",
        starred=True,
        published=datetime(2026, 10, 27, tzinfo=timezone.utc),
        label=python,
    )
    second = seed_item(
        db_session,
        feed,
        guid="rust-release",
        title="Rust release",
        content="Tokio ships a new version",
        is_read=True,
        published=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    third = seed_item(
        db_session,
        feed,
        guid="python-notes",
        title="Python notes",
        content="Asyncio patterns",
    )

    assert client.get("/api/items").json()["total"] == 3
    assert client.get("/api/items?unread=true").json()["total"] == 2
    assert client.get("/api/items?starred=true").json()["total"] == 1
    assert client.get(f"/api/items?feed_id={feed.id}").json()["total"] == 3
    assert client.get("/api/items?label=python").json()["total"] == 1
    assert client.get("/api/items?q=fastapi").json()["total"] == 1

    page = client.get("/api/items?limit=1&offset=1").json()
    assert page["total"] == 3
    assert len(page["items"]) == 1

    updated = client.patch(
        f"/api/items/{first.id}",
        json={
            "is_read": True,
            "starred": False,
            "decision": "keep",
            "label_ids": [],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["is_read"] is True
    assert updated.json()["starred"] is False
    assert updated.json()["decision"] == "keep"
    assert updated.json()["labels"] == []

    assert client.patch(f"/api/items/{second.id}", json={"decision": None}).status_code == 200
    assert client.get(f"/api/items/{third.id}").status_code == 200
    assert client.get("/api/items/9999").status_code == 404
    assert client.patch("/api/items/9999", json={"is_read": True}).status_code == 404


def test_item_exposes_sanitized_content_html(client: TestClient, db_session: Session) -> None:
    feed = seed_feed(db_session)
    item = seed_item(db_session, feed, guid="html-item", title="HTML post")
    item.content_html = "<p>Hello <a href=\"https://example.com\">there</a>.</p>"
    db_session.commit()

    body = client.get(f"/api/items/{item.id}").json()

    assert body["content_html"] == item.content_html
    assert body["content"] == ""


def test_item_labels_can_be_added_and_removed(client: TestClient, db_session: Session) -> None:
    feed = seed_feed(db_session)
    item = seed_item(db_session, feed, guid="item-1", title="A post")

    created = client.post("/api/labels", json={"name": "python"})
    assert created.status_code == 201
    label_id = created.json()["id"]
    assert client.post("/api/labels", json={"name": "python"}).status_code == 409
    assert client.post("/api/labels", json={"name": "  "}).status_code == 422

    attached = client.post(f"/api/items/{item.id}/labels/{label_id}")
    assert attached.status_code == 200
    assert [label["name"] for label in attached.json()["labels"]] == ["python"]

    assert client.delete(f"/api/items/{item.id}/labels/{label_id}").status_code == 204
    refreshed = client.get(f"/api/items/{item.id}").json()
    assert refreshed["labels"] == []
    assert client.delete(f"/api/labels/{label_id}").status_code == 204


def test_pipe_crud_and_validation(client: TestClient) -> None:
    payload = {
        "name": "One item",
        "spec_json": {"name": "One item", "steps": [{"box": "limit", "count": 1}]},
    }
    created = client.post("/api/pipes", json=payload)

    assert created.status_code == 201
    pipe_id = created.json()["id"]
    assert len(client.get("/api/pipes").json()) == 1
    assert client.get(f"/api/pipes/{pipe_id}").status_code == 200

    patched = client.patch(
        f"/api/pipes/{pipe_id}",
        json={"name": "Renamed", "spec_json": {"steps": [{"box": "limit", "count": 2}]}},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"

    invalid = client.post(
        "/api/pipes",
        json={"name": "Bad", "spec_json": {"steps": [{"box": "unknown"}]}},
    )
    assert invalid.status_code == 422

    assert client.delete(f"/api/pipes/{pipe_id}").status_code == 204
    assert client.get(f"/api/pipes/{pipe_id}").status_code == 404


def test_run_saved_pipe_returns_items_and_records_the_run(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = client.post(
        "/api/pipes",
        json={
            "name": "Fetch two",
            "spec_json": {
                "name": "Fetch two",
                "steps": [
                    {"box": "fetch", "urls": ["https://example.com/feed.xml"]},
                    {"box": "limit", "count": 2},
                ],
            },
        },
    ).json()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(handler))

    response = client.post(f"/api/pipes/{pipe['id']}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "success"
    assert body["run"]["result_count"] == 2
    assert [item["title"] for item in body["items"]] == ["API one", "API two"]
    assert [step["box"] for step in body["steps"]] == ["fetch", "limit"]

    runs = client.get(f"/api/runs?pipe_id={pipe['id']}").json()
    assert len(runs) == 1
    assert client.get(f"/api/runs/{runs[0]['id']}").status_code == 200


def test_failed_run_is_recorded(client: TestClient, monkeypatch) -> None:
    pipe = client.post(
        "/api/pipes",
        json={
            "name": "Broken",
            "spec_json": {
                "name": "Broken",
                "steps": [{"box": "fetch", "urls": ["https://example.com/missing.xml"]}],
            },
        },
    ).json()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(handler))

    response = client.post(f"/api/pipes/{pipe['id']}/run")

    assert response.status_code == 422
    runs = client.get(f"/api/runs?pipe_id={pipe['id']}").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert "HTTPStatusError" in runs[0]["error"]
