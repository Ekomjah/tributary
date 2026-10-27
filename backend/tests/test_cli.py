from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tributary.cli import app
from tributary.services import feeds

runner = CliRunner()


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

    def fake_fetch(session, url, *, client):
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

    def fake_fetch(session, url, *, client):
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


def test_unimplemented_commands_fail_loudly() -> None:
    run_result = runner.invoke(app, ["run", "pipe.json"])
    export_result = runner.invoke(app, ["export"])

    assert run_result.exit_code == 2
    assert "phase 3" in run_result.output
    assert export_result.exit_code == 2
    assert "phase 5" in export_result.output
