from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import Settings, get_settings
from .db import create_engine, init_db

app = typer.Typer(
    name="tributary",
    help="Tributary feed reader and pipe engine.",
    no_args_is_help=True,
    add_completion=False,
)


def _settings_with_db_path(settings: Settings, db_path: Path | None) -> Settings:
    if db_path is None:
        return settings
    return settings.model_copy(update={"db_path": db_path.expanduser().resolve()})


def _load_settings(db_path: Path | None = None) -> Settings:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    return _settings_with_db_path(settings, db_path)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tributary {__version__}")
        raise typer.Exit()


def _not_implemented(phase: str) -> None:
    typer.echo(f"This command is part of {phase} and is not implemented yet.", err=True)
    raise typer.Exit(code=2)


@app.callback()
def callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Run pipes and manage the local Tributary feed database."""


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Host to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to bind.")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Reload on code changes.")] = False,
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Run the API and reader."""
    import uvicorn

    settings = _load_settings(db)
    host = host or settings.host
    port = port or settings.port

    if db is not None:
        os.environ["TRIBUTARY_DB_PATH"] = str(settings.db_path)

    if reload:
        uvicorn.run(
            "tributary.main:app",
            host=host,
            port=port,
            reload=True,
            log_level=settings.log_level.lower(),
        )
    else:
        from .main import create_app

        uvicorn.run(
            create_app(settings),
            host=host,
            port=port,
            log_level=settings.log_level.lower(),
        )


@app.command("init-db")
def init_database(
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Create the database tables."""
    settings = _load_settings(db)
    engine = create_engine(settings)
    try:
        init_db(engine)
    finally:
        engine.dispose()
    typer.echo(f"Initialized database at {settings.db_path}")


@app.command("fetch")
def fetch_feed(
    url: Annotated[str, typer.Argument(help="Feed URL to fetch and store.")],
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Fetch and store one feed."""
    _load_settings(db)
    _not_implemented("phase 2")


@app.command("refresh")
def refresh_feeds(
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Refresh every subscription."""
    _load_settings(db)
    _not_implemented("phase 3")


@app.command("run")
def run_pipe(
    path: Annotated[Path, typer.Argument(help="Path to a pipe JSON file.")],
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Run a pipe JSON file."""
    _load_settings(db)
    _not_implemented("phase 3")


@app.command("export")
def export_training(
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Export labelled items as JSONL."""
    _load_settings(db)
    _not_implemented("phase 5")


def main() -> None:
    app()


if __name__ == "__main__":
    app()
