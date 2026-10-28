from __future__ import annotations

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from tributary.cli import app
from tributary.services import feeds

runner = CliRunner()

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>CLI Feed</title>
    <link>https://example.com/</link>
    <description>A CLI feed</description>
    <item>
      <title>CLI post</title>
      <link>https://example.com/posts/cli</link>
      <guid>cli-1</guid>
      <pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>
      <description>CLI body.</description>
    </item>
  </channel>
</rss>
"""


def test_help_exits_cleanly() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Usage" in result.output


def test_version_is_available() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "tributary 0.1.0" in result.output


def test_init_db_creates_the_database(tmp_path: Path) -> None:
    db_path = tmp_path / "cli.db"

    result = runner.invoke(app, ["init-db", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Initialized database" in result.output
    assert db_path.exists()


def test_fetch_reports_new_items(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"

    def fake_fetch(session, url, *, client, min_full_chars=500):
        return feeds.FetchResult(
            url=url,
            feed_id=1,
            title="Example",
            new_items=2,
            total_entries=3,
        )

    monkeypatch.setattr(feeds, "fetch_feed", fake_fetch)

    result = runner.invoke(
        app,
        ["fetch", "https://example.com/feed.xml", "--db", str(db_path)],
    )

    assert result.exit_code == 0
    assert "Example: 2 new" in result.output
    assert db_path.exists()


def test_fetch_exits_nonzero_on_feed_errors(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"

    def fake_fetch(session, url, *, client, min_full_chars=500):
        return feeds.FetchResult(url=url, error="HTTPStatusError: 404")

    monkeypatch.setattr(feeds, "fetch_feed", fake_fetch)

    result = runner.invoke(
        app,
        ["fetch", "https://example.com/missing.xml", "--db", str(db_path)],
    )

    assert result.exit_code == 1
    assert "404" in result.output


def test_refresh_without_feeds_succeeds(tmp_path: Path) -> None:
    db_path = tmp_path / "cli.db"

    result = runner.invoke(app, ["refresh", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "No feeds yet" in result.output


def test_export_is_not_implemented() -> None:
    result = runner.invoke(app, ["export"])

    assert result.exit_code == 2
    assert "not implemented yet" in result.output


def test_run_executes_a_pipe_file(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    pipe_path = tmp_path / "pipe.json"
    pipe_path.write_text(
        json.dumps(
            {
                "name": "CLI pipe",
                "steps": [
                    {"box": "fetch", "urls": ["https://example.com/feed.xml"]},
                    {"box": "limit", "count": 1},
                ],
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    def fake_make_client(settings):
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("tributary.cli.feeds.make_client", fake_make_client)

    result = runner.invoke(app, ["run", str(pipe_path), "--db", str(db_path)])

    assert result.exit_code == 0
    assert "CLI pipe: 1 item(s)" in result.output
    assert "CLI post" in result.output


def test_run_can_print_json(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    pipe_path = tmp_path / "pipe.json"
    pipe_path.write_text(
        json.dumps(
            {
                "steps": [
                    {"box": "fetch", "urls": ["https://example.com/feed.xml"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    def fake_make_client(settings):
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("tributary.cli.feeds.make_client", fake_make_client)

    result = runner.invoke(app, ["run", str(pipe_path), "--db", str(db_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["title"] == "CLI post"


def test_run_reports_invalid_pipes(tmp_path: Path) -> None:
    pipe_path = tmp_path / "bad.json"
    pipe_path.write_text("{", encoding="utf-8")

    result = runner.invoke(app, ["run", str(pipe_path), "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 1
    assert "not valid JSON" in result.output
