from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tributary.cli import app

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


def test_unimplemented_commands_fail_loudly() -> None:
    result = runner.invoke(app, ["fetch", "https://example.com/feed.xml"])

    assert result.exit_code == 2
    assert "phase 2" in result.output
