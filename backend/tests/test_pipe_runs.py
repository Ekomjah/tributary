from __future__ import annotations

import time

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tributary.boxes import plain
from tributary.db import ensure_local_user
from tributary.models import Pipe, Run
from tributary.services import feeds, pipe_runs

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Pipe Run</title>
    <link>https://example.com/</link>
    <description>A pipe run</description>
    <item>
      <title>API one</title>
      <link>https://example.com/posts/one</link>
      <guid>run-1</guid>
      <pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>
      <description>First body.</description>
    </item>
    <item>
      <title>API two</title>
      <link>https://example.com/posts/two</link>
      <guid>run-2</guid>
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
        json={"name": "Async pipe", "spec_json": {"name": "Async pipe", "steps": steps}},
    )
    assert response.status_code == 201
    return response.json()


def wait_for_run(client: TestClient, run_id: int, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not finish within {timeout}s")


def test_start_pipe_run_returns_202_and_completes_in_background(
    client: TestClient,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [
            {"box": "fetch", "urls": [FEED_URL]},
            {"box": "limit", "count": 2},
        ],
    )
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))

    response = client.post(f"/api/pipes/{pipe['id']}/runs")

    assert response.status_code == 202
    started = response.json()
    assert started["status"] == "running"
    assert started["result_count"] == 0

    run = wait_for_run(client, started["id"])

    assert run["status"] == "success"
    assert run["result_count"] == 2
    results = client.get(f"/api/runs/{run['id']}/results").json()
    assert [item["title"] for item in results["items"]] == ["API one", "API two"]
    assert [step["box"] for step in results["steps"]] == ["fetch", "limit"]


def test_failed_step_is_attributed_on_the_run(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [
            {"box": "fetch", "urls": [FEED_URL]},
            {"box": "limit", "count": 2},
        ],
    )

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(
        feeds,
        "make_client",
        lambda settings: mock_client(failing_handler),
    )

    response = client.post(f"/api/pipes/{pipe['id']}/runs")
    run = wait_for_run(client, response.json()["id"])

    assert run["status"] == "error"
    assert run["error_box"] == "fetch"
    assert run["error_step"] == 0
    assert "fetch step failed" in run["error"]

    results = client.get(f"/api/runs/{run['id']}/results").json()
    assert [step["box"] for step in results["steps"]] == ["fetch"]
    assert results["steps"][0]["status"] == "error"
    assert "HTTPStatusError" in results["steps"][0]["error"]

    db_session.expire_all()
    stored = db_session.get(Run, run["id"])
    assert stored is not None
    assert stored.error_box == "fetch"
    assert stored.error_step == 0
    assert stored.steps_json[0]["status"] == "error"


def test_partial_steps_survive_a_later_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    pipe = create_pipe(
        client,
        [
            {"box": "fetch", "urls": [FEED_URL]},
            {"box": "limit", "count": 2},
        ],
    )
    monkeypatch.setattr(feeds, "make_client", lambda settings: mock_client(rss_handler))

    def boom(self, items, context):  # noqa: ANN001
        raise RuntimeError("kaboom")

    monkeypatch.setattr(plain.LimitBox, "run", boom)

    response = client.post(f"/api/pipes/{pipe['id']}/runs")
    run = wait_for_run(client, response.json()["id"])

    assert run["status"] == "error"
    assert run["error_box"] == "limit"
    assert run["error_step"] == 1

    results = client.get(f"/api/runs/{run['id']}/results").json()
    assert [step["box"] for step in results["steps"]] == ["fetch", "limit"]
    assert [step["status"] for step in results["steps"]] == ["success", "error"]
    assert "kaboom" in results["steps"][1]["error"]


def test_reap_interrupted_runs_marks_running_rows_failed(
    session_factory: sessionmaker[Session],
    db_session: Session,
) -> None:
    pipe = Pipe(
        owner_id=ensure_local_user(db_session).id,
        name="Interrupted",
        spec_json={"name": "Interrupted", "steps": [{"box": "limit", "count": 1}]},
    )
    db_session.add(pipe)
    db_session.commit()
    db_session.refresh(pipe)

    run = Run(pipe_id=pipe.id, status="running")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert pipe_runs.reap_interrupted_runs(session_factory) == 1

    db_session.expire_all()
    stored = db_session.get(Run, run.id)
    assert stored is not None
    assert stored.status == "error"
    assert "interrupted" in (stored.error or "")
    assert stored.result_count == 0


def test_app_startup_reaps_runs_left_by_a_previous_process(
    settings,
    db_session: Session,
) -> None:
    from tributary.main import create_app

    pipe = Pipe(
        owner_id=ensure_local_user(db_session).id,
        name="Restarted",
        spec_json={"name": "Restarted", "steps": [{"box": "limit", "count": 1}]},
    )
    db_session.add(pipe)
    db_session.commit()
    db_session.refresh(pipe)

    run = Run(pipe_id=pipe.id, status="running")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    with TestClient(create_app(settings)) as startup_client:
        body = startup_client.get(f"/api/runs/{run.id}").json()

    assert body["status"] == "error"
    assert "interrupted" in body["error"]
