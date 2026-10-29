from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tributary.models import Feed, Item, Run, pipe_feed_items
from tributary.services import feeds

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Pipe Feed</title>
    <link>https://example.com/</link>
    <description>A pipe feed</description>
    <item>
      <title>API one</title>
      <link>https://example.com/posts/one</link>
      <guid>pipe-1</guid>
      <pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>
      <description>First body.</description>
    </item>
    <item>
      <title>API two</title>
      <link>https://example.com/posts/two</link>
      <guid>pipe-2</guid>
      <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
      <description>Second body.</description>
    </item>
  </channel>
</rss>
"""

FEED_URL = "https://example.com/feed.xml"


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def rss_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=RSS.encode())


def create_pipe(client: TestClient, steps: list[dict]) -> dict:
    response = client.post(
        "/api/pipes",
        json={"name": "Reader pipe", "spec_json": {"name": "Reader pipe", "steps": steps}},
    )
    assert response.status_code == 201
    return response.json()


def add_pipe_feed(client: TestClient, pipe_id: int) -> dict:
    response = client.post("/api/feeds/pipe", json={"pipe_id": pipe_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_add_pipe_feed_runs_the_pipe_and_is_idempotent(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [
            {"box": "fetch", "urls": [FEED_URL]},
            {"box": "sort", "by": "title", "order": "desc"},
            {"box": "limit", "count": 2},
        ],
    )
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))

    first = add_pipe_feed(client, pipe["id"])

    assert first["created"] is True
    assert first["items"] == 2
    assert first["error"] is None
    assert first["feed"]["kind"] == "pipe"
    assert first["feed"]["pipe_id"] == pipe["id"]
    assert first["feed"]["url"] == f"pipe://{pipe['id']}"

    feed_id = first["feed"]["id"]
    listed = client.get(f"/api/items?feed_id={feed_id}").json()
    assert listed["total"] == 2
    assert [item["title"] for item in listed["items"]] == ["API two", "API one"]

    second = add_pipe_feed(client, pipe["id"])

    assert second["created"] is False
    assert second["feed"]["id"] == feed_id
    assert second["items"] == 2
    pipe_feeds = [feed for feed in client.get("/api/feeds").json() if feed["kind"] == "pipe"]
    assert len(pipe_feeds) == 1
    # Adding an existing pipe feed does not start another run.
    assert len(client.get(f"/api/runs?pipe_id={pipe['id']}").json()) == 1


def test_refresh_pipe_feed_replaces_membership_and_order(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [
            {"box": "fetch", "urls": [FEED_URL]},
            {"box": "sort", "by": "title", "order": "desc"},
            {"box": "limit", "count": 1},
        ],
    )
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))
    added = add_pipe_feed(client, pipe["id"])
    feed_id = added["feed"]["id"]
    assert [
        item["title"]
        for item in client.get(f"/api/items?feed_id={feed_id}").json()["items"]
    ] == ["API two"]

    updated = client.patch(
        f"/api/pipes/{pipe['id']}",
        json={
            "spec_json": {
                "name": "Reader pipe",
                "steps": [
                    {"box": "fetch", "urls": [FEED_URL]},
                    {"box": "sort", "by": "title", "order": "asc"},
                    {"box": "limit", "count": 2},
                ],
            }
        },
    )
    assert updated.status_code == 200

    response = client.post(f"/api/feeds/{feed_id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "pipe"
    assert body["feed_id"] == feed_id
    assert body["new_items"] == 2
    assert body["error"] is None

    listed = client.get(f"/api/items?feed_id={feed_id}").json()
    assert listed["total"] == 2
    assert [item["title"] for item in listed["items"]] == ["API one", "API two"]


def test_failed_pipe_feed_add_records_an_error_run(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [{"box": "fetch", "urls": ["https://example.com/missing.xml"]}],
    )

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(failing_handler))

    response = client.post("/api/feeds/pipe", json={"pipe_id": pipe["id"]})

    assert response.status_code == 502
    assert "HTTPStatusError" in response.json()["detail"]
    assert client.get("/api/feeds").json() == []
    runs = client.get(f"/api/runs?pipe_id={pipe['id']}").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"


def test_failed_pipe_feed_refresh_keeps_previous_membership(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(client, [{"box": "fetch", "urls": [FEED_URL]}])
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))
    feed_id = add_pipe_feed(client, pipe["id"])["feed"]["id"]

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(failing_handler))
    response = client.post(f"/api/feeds/{feed_id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "pipe"
    assert body["new_items"] == 2
    assert "HTTPStatusError" in body["error"]
    assert client.get(f"/api/feeds/{feed_id}").json()["last_error"] is not None

    listed = client.get(f"/api/items?feed_id={feed_id}").json()
    assert listed["total"] == 2


def test_deleting_a_pipe_removes_its_reader_feed_but_not_items(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(client, [{"box": "fetch", "urls": [FEED_URL]}])
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))
    added = add_pipe_feed(client, pipe["id"])
    feed_id = added["feed"]["id"]

    response = client.delete(f"/api/pipes/{pipe['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/feeds/{feed_id}").status_code == 404
    source = db_session.scalar(select(Feed).where(Feed.url == FEED_URL))
    assert source is not None
    assert len(db_session.scalars(select(Item).where(Item.feed_id == source.id)).all()) == 2
    assert db_session.scalars(select(pipe_feed_items)).all() == []


def test_deleting_a_pipe_reader_feed_keeps_the_pipe(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(client, [{"box": "fetch", "urls": [FEED_URL]}])
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))
    feed_id = add_pipe_feed(client, pipe["id"])["feed"]["id"]

    assert client.delete(f"/api/feeds/{feed_id}").status_code == 204

    assert client.get(f"/api/pipes/{pipe['id']}").status_code == 200
    assert [feed for feed in client.get("/api/feeds").json() if feed["kind"] == "pipe"] == []


def test_global_refresh_skips_pipe_feeds(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(client, [{"box": "fetch", "urls": [FEED_URL]}])
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))
    add_pipe_feed(client, pipe["id"])

    response = client.post("/api/feeds/refresh")

    assert response.status_code == 200
    urls = [result["url"] for result in response.json()]
    assert urls == [FEED_URL]


def test_pipe_run_history_reconstructs_ordered_results(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [
            {"box": "fetch", "urls": [FEED_URL]},
            {"box": "sort", "by": "title", "order": "desc"},
            {"box": "limit", "count": 2},
        ],
    )
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))

    run_response = client.post(f"/api/pipes/{pipe['id']}/run")
    assert run_response.status_code == 200
    run_id = run_response.json()["run"]["id"]

    stored = db_session.get(Run, run_id)
    assert stored is not None
    assert [step["box"] for step in stored.steps_json] == ["fetch", "sort", "limit"]
    assert stored.item_ids_json == [
        item["id"] for item in run_response.json()["items"]
    ]

    history = client.get(f"/api/runs/{run_id}/results")

    assert history.status_code == 200
    body = history.json()
    assert body["run"]["id"] == run_id
    assert [item["title"] for item in body["items"]] == ["API two", "API one"]
    assert [step["box"] for step in body["steps"]] == ["fetch", "sort", "limit"]


def test_run_history_skips_items_deleted_after_the_run(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [{"box": "fetch", "urls": [FEED_URL]}, {"box": "limit", "count": 2}],
    )
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))
    run = client.post(f"/api/pipes/{pipe['id']}/run").json()
    deleted_id = run["items"][0]["id"]

    item = db_session.get(Item, deleted_id)
    assert item is not None
    db_session.delete(item)
    db_session.commit()

    history = client.get(f"/api/runs/{run['run']['id']}/results").json()

    assert [item["id"] for item in history["items"]] == [
        item["id"] for item in run["items"][1:]
    ]
