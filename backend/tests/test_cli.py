from __future__ import annotations

from pathlib import Path

import pytest

from tributary.cli import main


def test_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0


def test_init_db_creates_the_database(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "cli.db"

    assert main(["init-db", "--db", str(db_path)]) == 0

    assert db_path.exists()
    assert "Initialized database" in capsys.readouterr().out


def test_unimplemented_commands_fail_loudly() -> None:
    assert main(["fetch", "https://example.com/feed.xml"]) == 2
