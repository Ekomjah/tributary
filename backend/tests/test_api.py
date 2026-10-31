from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tributary.db import ensure_local_user
from tributary.models import Feed, Item, Label, Pipe, Run, User
from tributary.services import articles, feeds

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
    feed = Feed(owner_id=ensure_local_user(db).id, url=url, title=title)
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
    python = Label(owner_id=ensure_local_user(db_session).id, name="python")
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


def test_item_exposes_article_frontmatter(client: TestClient, db_session: Session) -> None:
    feed = seed_feed(db_session)
    item = seed_item(db_session, feed, guid="frontmatter-item", title="Frontmatter post")
    item.author = "Jane Doe"
    item.cover_image = "https://example.com/cover.jpg"
    item.cover_image_alt = "A wide cover"
    item.cover_caption = "The cover caption."
    db_session.commit()

    body = client.get(f"/api/items/{item.id}").json()

    assert body["author"] == "Jane Doe"
    assert body["cover_image"] == "https://example.com/cover.jpg"
    assert body["cover_image_alt"] == "A wide cover"
    assert body["cover_caption"] == "The cover caption."


def test_fetch_item_article_returns_frontmatter(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    feed = seed_feed(db_session)
    item = seed_item(db_session, feed, guid="fetch-frontmatter", title="Example")

    paragraph = "A substantial sentence about the article topic. " * 12
    page = (
        "<html><head><title>Example</title>"
        '<meta name="author" content="Jane Doe">'
        '<meta property="og:image" content="https://example.com/branded/1200/abc123.jpg">'
        "</head><body><article>"
        '<figure><img src="https://example.com/standard/1920/abc123.jpg" alt="A cover">'
        "<figcaption>The cover caption.</figcaption></figure>"
        + "".join(f"<p>{paragraph}</p>" for _ in range(3))
        + "</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=page.encode(),
        )

    monkeypatch.setattr(articles, "make_client", lambda settings: mock_client(handler))

    response = client.post(f"/api/items/{item.id}/fetch")

    assert response.status_code == 200
    body = response.json()
    assert body["author"] == "Jane Doe"
    assert body["cover_image"] == "https://example.com/standard/1920/abc123.jpg"
    assert body["cover_image_alt"] == "A cover"
    assert body["content_html"] is not None
    assert "abc123.jpg" not in body["content_html"]
    assert body["fetch_status"] == "ok"


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


def test_cross_tenant_rows_are_invisible_and_immutable(
    client: TestClient,
    db_session: Session,
) -> None:
    local = ensure_local_user(db_session)
    other = User(
        auth0_sub="auth0|other",
        name="Other",
        last_seen_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )
    db_session.add(other)
    db_session.flush()

    other_feed = Feed(
        owner_id=other.id,
        url="https://other.example/feed.xml",
        title="Other feed",
    )
    other_label = Label(owner_id=other.id, name="Secret")
    other_pipe = Pipe(
        owner_id=other.id,
        name="Other pipe",
        spec_json={"steps": []},
    )
    db_session.add_all([other_feed, other_label, other_pipe])
    db_session.flush()

    other_item = Item(
        feed_id=other_feed.id,
        guid="other-item",
        title="Other item",
        content="Private",
        fetched_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )
    db_session.add(other_item)
    db_session.flush()
    other_item.labels.append(other_label)
    other_run = Run(
        pipe_id=other_pipe.id,
        status="success",
        result_count=1,
        item_ids_json=[other_item.id],
        steps_json=[],
    )
    db_session.add(other_run)
    db_session.commit()

    assert client.get("/api/feeds").json() == []
    assert client.get("/api/labels").json() == []
    assert client.get("/api/pipes").json() == []
    assert client.get("/api/items").json()["total"] == 0
    assert client.get(f"/api/items?feed_id={other_feed.id}").status_code == 404
    assert client.get("/api/runs").json() == []

    assert client.get(f"/api/feeds/{other_feed.id}").status_code == 404
    assert client.delete(f"/api/feeds/{other_feed.id}").status_code == 404
    assert client.post(f"/api/feeds/{other_feed.id}/refresh").status_code == 404
    assert client.post("/api/feeds/pipe", json={"pipe_id": other_pipe.id}).status_code == 404

    assert client.get(f"/api/items/{other_item.id}").status_code == 404
    assert client.patch(
        f"/api/items/{other_item.id}",
        json={"is_read": True},
    ).status_code == 404
    assert client.post(f"/api/items/{other_item.id}/fetch").status_code == 404
    assert client.post(
        f"/api/items/{other_item.id}/labels/{other_label.id}"
    ).status_code == 404
    assert client.delete(
        f"/api/items/{other_item.id}/labels/{other_label.id}"
    ).status_code == 404
    assert client.delete(f"/api/labels/{other_label.id}").status_code == 404

    created_label = client.post("/api/labels", json={"name": "secret"})
    assert created_label.status_code == 201
    assert created_label.json()["id"] != other_label.id

    assert client.get(f"/api/pipes/{other_pipe.id}").status_code == 404
    assert client.patch(
        f"/api/pipes/{other_pipe.id}",
        json={"name": "Mine"},
    ).status_code == 404
    assert client.delete(f"/api/pipes/{other_pipe.id}").status_code == 404
    assert client.post(f"/api/pipes/{other_pipe.id}/run").status_code == 404
    assert client.post(f"/api/pipes/{other_pipe.id}/runs").status_code == 404
    assert client.get(f"/api/runs?pipe_id={other_pipe.id}").status_code == 404
    assert client.get(f"/api/runs/{other_run.id}").status_code == 404
    assert client.get(f"/api/runs/{other_run.id}/results").status_code == 404

    own_feed = Feed(
        owner_id=local.id,
        url="https://mine.example/feed.xml",
        title="Mine",
    )
    own_pipe = Pipe(owner_id=local.id, name="Mine", spec_json={"steps": []})
    db_session.add_all([own_feed, own_pipe])
    db_session.flush()
    own_item = Item(
        feed_id=own_feed.id,
        guid="own-item",
        title="Mine",
        content="Mine",
        fetched_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )
    db_session.add(own_item)
    db_session.flush()
    own_run = Run(
        pipe_id=own_pipe.id,
        status="success",
        result_count=2,
        item_ids_json=[other_item.id, own_item.id],
        steps_json=[],
    )
    db_session.add(own_run)
    db_session.commit()

    results = client.get(f"/api/runs/{own_run.id}/results")
    assert results.status_code == 200
    assert [item["id"] for item in results.json()["items"]] == [own_item.id]


def test_refresh_all_only_touches_the_current_tenant(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    local = ensure_local_user(db_session)
    other = User(
        auth0_sub="auth0|other",
        name="Other",
        last_seen_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )
    db_session.add(other)
    db_session.flush()
    db_session.add_all(
        [
            Feed(
                owner_id=local.id,
                url="https://mine.example/feed.xml",
                title="Mine",
            ),
            Feed(
                owner_id=other.id,
                url="https://other.example/feed.xml",
                title="Other",
            ),
        ]
    )
    db_session.commit()

    called: list[tuple[str, int]] = []

    def fake_fetch(session, url, *, owner_id, client, min_full_chars=500):
        called.append((url, owner_id))
        return feeds.FetchResult(
            url=url,
            feed_id=1,
            title="Mine",
            new_items=0,
            total_entries=0,
        )

    monkeypatch.setattr(feeds, "fetch_feed", fake_fetch)

    response = client.post("/api/feeds/refresh")

    assert response.status_code == 200
    assert called == [("https://mine.example/feed.xml", local.id)]
