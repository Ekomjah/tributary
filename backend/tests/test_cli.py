from __future__ import annotations

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from tributary.cli import app
from tributary.config import ConfigurationError, Settings
from tributary.db import create_engine, create_session_factory, init_db, session_scope
from tributary.models import Feed, Item
from tributary.services import discovery, feeds, refine
from tributary.services import search as web_search
from tributary.services.refine import RefinementOutcome, SearchSpec
from tributary.services.search import SearchOutcome

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
        [
            "fetch",
            "https://example.com/feed.xml",
            "--no-discover",
            "--db",
            str(db_path),
        ],
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
        [
            "fetch",
            "https://example.com/missing.xml",
            "--no-discover",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 1
    assert "404" in result.output


def test_discover_prints_candidates(monkeypatch) -> None:
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

    monkeypatch.setattr(
        feeds,
        "make_client",
        lambda settings: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = runner.invoke(app, ["discover", "example.com/blog"])

    assert result.exit_code == 0
    assert "Example Blog" in result.output
    assert "https://example.com/feed.xml" in result.output


def test_discover_can_print_json(monkeypatch) -> None:
    result_obj = discovery.DiscoveryResult(
        input_url="https://example.com/blog",
        page_title="Example Blog",
        candidates=[
            discovery.FeedCandidate(
                url="https://example.com/feed.xml",
                title="Example Feed",
                kind="rss",
            )
        ],
    )
    monkeypatch.setattr(discovery, "discover_feed", lambda client, url: result_obj)
    monkeypatch.setattr(feeds, "make_client", lambda settings: httpx.Client())

    result = runner.invoke(app, ["discover", "https://example.com/blog", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "input_url": "https://example.com/blog",
        "page_title": "Example Blog",
        "candidates": [
            {
                "url": "https://example.com/feed.xml",
                "title": "Example Feed",
                "kind": "rss",
            }
        ],
    }


def test_discover_exits_nonzero_without_a_feed(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery,
        "discover_feed",
        lambda client, url: discovery.DiscoveryResult(input_url=url),
    )
    monkeypatch.setattr(feeds, "make_client", lambda settings: httpx.Client())

    result = runner.invoke(app, ["discover", "https://example.com/blog"])

    assert result.exit_code == 1
    assert "No feed found" in result.output


def test_fetch_discovers_the_feed_first(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    seen: dict[str, str] = {}

    def fake_discover(client, url):
        return discovery.DiscoveryResult(
            input_url=url,
            candidates=[
                discovery.FeedCandidate(
                    url="https://example.com/feed.xml",
                    title="Found Feed",
                    kind="rss",
                )
            ],
        )

    def fake_fetch(session, url, *, client, min_full_chars=500):
        seen["url"] = url
        return feeds.FetchResult(url=url, feed_id=1, title="Found Feed", new_items=1)

    monkeypatch.setattr(discovery, "discover_feed", fake_discover)
    monkeypatch.setattr(feeds, "fetch_feed", fake_fetch)
    monkeypatch.setattr(feeds, "make_client", lambda settings: httpx.Client())

    result = runner.invoke(
        app,
        ["fetch", "https://example.com/blog", "--db", str(db_path)],
    )

    assert result.exit_code == 0
    assert seen["url"] == "https://example.com/feed.xml"
    assert "Found Feed: 1 new" in result.output


def test_fetch_no_discover_uses_the_exact_url(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    seen: dict[str, str] = {}

    def fail_discover(client, url):
        raise AssertionError("discovery should not run with --no-discover")

    def fake_fetch(session, url, *, client, min_full_chars=500):
        seen["url"] = url
        return feeds.FetchResult(url=url, feed_id=1, title="Exact", new_items=0)

    monkeypatch.setattr(discovery, "discover_feed", fail_discover)
    monkeypatch.setattr(feeds, "fetch_feed", fake_fetch)

    result = runner.invoke(
        app,
        [
            "fetch",
            "https://example.com/feed.xml",
            "--no-discover",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0
    assert seen["url"] == "https://example.com/feed.xml"


def test_fetch_exits_two_for_multiple_candidates(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"

    def fake_discover(client, url):
        return discovery.DiscoveryResult(
            input_url=url,
            candidates=[
                discovery.FeedCandidate(url="https://example.com/one.xml", kind="rss"),
                discovery.FeedCandidate(url="https://example.com/two.xml", kind="atom"),
            ],
        )

    def fail_fetch(*args, **kwargs):
        raise AssertionError("fetch should not run until a candidate is chosen")

    monkeypatch.setattr(discovery, "discover_feed", fake_discover)
    monkeypatch.setattr(feeds, "fetch_feed", fail_fetch)
    monkeypatch.setattr(feeds, "make_client", lambda settings: httpx.Client())

    result = runner.invoke(
        app,
        ["fetch", "https://example.com/blog", "--db", str(db_path)],
    )

    assert result.exit_code == 2
    assert "https://example.com/one.xml" in result.output
    assert "https://example.com/two.xml" in result.output


def test_refresh_without_feeds_succeeds(tmp_path: Path) -> None:
    db_path = tmp_path / "cli.db"

    result = runner.invoke(app, ["refresh", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "No feeds yet" in result.output


def seed_labelled_item(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIBUTARY_DB_PATH", str(db_path))
    settings = Settings(_env_file=None)
    engine = create_engine(settings)
    try:
        init_db(engine)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            feed = Feed(url="https://example.com/feed.xml", title="Example")
            session.add(feed)
            session.flush()
            session.add(
                Item(
                    feed_id=feed.id,
                    guid="keep-1",
                    title="Keep this",
                    link="https://example.com/keep",
                    content="Short.",
                    content_full="The full article text.",
                    decision="keep",
                    starred=True,
                )
            )
            session.add(
                Item(
                    feed_id=feed.id,
                    guid="unlabelled-1",
                    title="Not labelled yet",
                    link="https://example.com/unlabelled",
                    content="Another body.",
                )
            )
    finally:
        engine.dispose()


def test_export_writes_labelled_items(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    out_path = tmp_path / "training.jsonl"
    seed_labelled_item(db_path, monkeypatch)

    result = runner.invoke(
        app,
        ["export", "--db", str(db_path), "--out", str(out_path)],
    )

    assert result.exit_code == 0
    assert "Wrote 1 item(s)" in result.output
    record = json.loads(out_path.read_text(encoding="utf-8").strip())
    assert record["label"] == "keep"
    assert record["starred"] is True
    assert record["text"] == "The full article text."
    assert record["feed"] == "Example"


def test_export_skips_unlabelled_items_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "cli.db"
    seed_labelled_item(db_path, monkeypatch)

    result = runner.invoke(app, ["export", "--db", str(db_path)])

    assert result.exit_code == 0
    assert json.loads(result.output)["title"] == "Keep this"

    labelled_only = runner.invoke(app, ["export", "--db", str(db_path), "--all"])
    assert labelled_only.exit_code == 0
    assert len(labelled_only.output.strip().splitlines()) == 2


def test_doctor_reports_a_healthy_setup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SENTRY_ENABLED", "false")
    monkeypatch.setattr(
        "tributary.cli.model.check_ollama",
        lambda settings: (True, "reachable at test", ["gemma3:1b"]),
    )

    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 0
    assert "OK    database" in result.output
    assert "OK    ollama" in result.output


def test_doctor_warns_when_the_model_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SENTRY_ENABLED", "false")
    monkeypatch.setattr(
        "tributary.cli.model.check_ollama",
        lambda settings: (True, "reachable at test", ["another-model:1b"]),
    )

    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 0
    assert "ollama pull gemma3:1b" in result.output


def test_doctor_reports_a_configuration_error_cleanly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail() -> Settings:
        raise ConfigurationError("OLLAMA_CLOUD=true requires OLLAMA_API_KEY")

    monkeypatch.setattr("tributary.cli.get_settings", fail)

    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 1
    assert (
        "Configuration error: OLLAMA_CLOUD=true requires OLLAMA_API_KEY"
        in result.output
    )


def test_doctor_reports_cloud_ollama_mode(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud=True,
        ollama_api_key="cloud-key",
        sentry_enabled=False,
    )
    monkeypatch.setattr("tributary.cli.get_settings", lambda: settings)
    monkeypatch.setattr(
        "tributary.cli.model.check_ollama",
        lambda settings: (
            True,
            "reachable at https://ollama.com",
            ["gemma4:3b"],
        ),
    )

    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 0
    assert "OK    ollama cloud" in result.output
    assert "gemma4:3b" in result.output
    assert "ollama pull" not in result.output


def test_doctor_cloud_model_missing_does_not_suggest_a_local_pull(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud=True,
        ollama_api_key="cloud-key",
        sentry_enabled=False,
    )
    monkeypatch.setattr("tributary.cli.get_settings", lambda: settings)
    monkeypatch.setattr(
        "tributary.cli.model.check_ollama",
        lambda settings: (True, "reachable at https://ollama.com", ["other:1b"]),
    )

    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 0
    assert "OLLAMA_CLOUD_MODEL" in result.output
    assert "ollama pull" not in result.output


def test_doctor_treats_a_missing_sentry_dsn_as_inactive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        _env_file=None,
        sentry_dsn=None,
        sentry_enabled=True,
    )
    monkeypatch.setattr("tributary.cli.get_settings", lambda: settings)
    monkeypatch.setattr("tributary.cli.init_sentry", lambda settings: None)
    monkeypatch.setattr(
        "tributary.cli.model.check_ollama",
        lambda settings: (True, "reachable at test", ["gemma3:1b"]),
    )

    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 0
    assert "OK    sentry    inactive" in result.output
    assert "WARN  sentry" not in result.output


def test_doctor_honors_an_explicit_tracing_opt_out(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        _env_file=None,
        sentry_dsn="https://public@example.com/1",
        sentry_enabled=True,
        sentry_traces_sample_rate=0,
    )
    monkeypatch.setattr("tributary.cli.get_settings", lambda: settings)
    monkeypatch.setattr("tributary.cli.init_sentry", lambda settings: None)
    monkeypatch.setattr(
        "tributary.cli.model.check_ollama",
        lambda settings: (True, "reachable at test", ["gemma3:1b"]),
    )

    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "cli.db")])

    assert result.exit_code == 0
    assert "errors on, tracing off" in result.output


def test_search_refines_and_shows_the_query(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("SERPAPI_API_KEY", "dummy")
    refined = RefinementOutcome(
        spec=SearchSpec(
            q="AI regulation",
            engine="google_news",
            gl="us",
            hl="en",
            freshness="week",
            max_results=6,
        ),
        fallback=False,
        model="fake:1b",
        seconds=0.2,
    )
    seen: dict[str, web_search.SearchParams] = {}

    def fake_run_search(session, settings, params, **kwargs):
        seen["params"] = params
        return SearchOutcome(
            query=str(kwargs.get("raw_query") or ""),
            params=params,
            items=[],
            cached=False,
            seconds=0.1,
        )

    monkeypatch.setattr(refine, "refine_query", lambda settings, query: refined)
    monkeypatch.setattr(web_search, "run_search", fake_run_search)

    result = runner.invoke(
        app,
        ["search", "AI regulation this week", "--db", str(db_path)],
    )

    assert result.exit_code == 0
    assert "Refined: 'AI regulation'" in result.output
    assert "via fake:1b" in result.output
    assert seen["params"].q == "AI regulation"
    assert seen["params"].freshness == "week"
    assert seen["params"].max_results == 6


def test_search_can_skip_refinement(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("SERPAPI_API_KEY", "dummy")
    seen: dict[str, web_search.SearchParams] = {}

    def fail_refine(settings, query):
        raise AssertionError("refinement should not run")

    def fake_run_search(session, settings, params, **kwargs):
        seen["params"] = params
        return SearchOutcome(
            query=str(kwargs.get("raw_query") or ""),
            params=params,
            items=[],
            cached=False,
            seconds=0.1,
        )

    monkeypatch.setattr(refine, "refine_query", fail_refine)
    monkeypatch.setattr(web_search, "run_search", fake_run_search)

    result = runner.invoke(
        app,
        ["search", "raw words", "--no-refine", "--db", str(db_path)],
    )

    assert result.exit_code == 0
    assert "Refined:" not in result.output
    assert seen["params"].q == "raw words"


def test_search_json_keeps_refinement_metadata_on_stderr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("SERPAPI_API_KEY", "dummy")
    refined = RefinementOutcome(
        spec=SearchSpec(q="AI regulation", freshness="week", max_results=5),
        fallback=True,
        model="fake:1b",
        seconds=0.3,
    )

    def fake_run_search(session, settings, params, **kwargs):
        return SearchOutcome(
            query=str(kwargs.get("raw_query") or ""),
            params=params,
            items=[],
            cached=False,
            seconds=0.1,
        )

    monkeypatch.setattr(refine, "refine_query", lambda settings, query: refined)
    monkeypatch.setattr(web_search, "run_search", fake_run_search)

    result = runner.invoke(
        app,
        ["search", "AI regulation this week", "--json", "--db", str(db_path)],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    metadata = json.loads(result.stderr)
    assert metadata["fallback"] is True
    assert metadata["spec"]["q"] == "AI regulation"
    assert metadata["model"] == "fake:1b"


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
