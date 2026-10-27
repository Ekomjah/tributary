from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import Settings, get_settings
from .db import create_engine, init_db


def _settings_with_db_path(settings: Settings, db_path: str | None) -> Settings:
    if db_path is None:
        return settings
    return settings.model_copy(update={"db_path": Path(db_path).expanduser().resolve()})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tributary", description="Tributary feed reader")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the API and reader")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="Reload on code changes")
    serve.add_argument("--db", default=None, help="Path to the SQLite database")

    init_db_parser = subparsers.add_parser("init-db", help="Create the database tables")
    init_db_parser.add_argument("--db", default=None, help="Path to the SQLite database")

    fetch = subparsers.add_parser("fetch", help="Fetch and store one feed")
    fetch.add_argument("url")
    fetch.add_argument("--db", default=None)

    refresh = subparsers.add_parser("refresh", help="Refresh every subscription")
    refresh.add_argument("--db", default=None)

    run = subparsers.add_parser("run", help="Run a pipe JSON file")
    run.add_argument("path")
    run.add_argument("--db", default=None)

    export = subparsers.add_parser("export", help="Export labelled items as JSONL")
    export.add_argument("--db", default=None)

    return parser


def _serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    settings = _settings_with_db_path(settings, args.db)
    host = args.host or settings.host
    port = args.port or settings.port

    if args.db:
        os.environ["TRIBUTARY_DB_PATH"] = str(settings.db_path)

    if args.reload:
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
    return 0


def _init_db(args: argparse.Namespace, settings: Settings) -> int:
    settings = _settings_with_db_path(settings, args.db)
    engine = create_engine(settings)
    try:
        init_db(engine)
    finally:
        engine.dispose()
    print(f"Initialized database at {settings.db_path}")
    return 0


def _not_implemented(phase: str) -> int:
    print(f"This command is part of {phase} and is not implemented yet.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "serve":
        return _serve(args, settings)
    if args.command == "init-db":
        return _init_db(args, settings)
    if args.command == "fetch":
        return _not_implemented("phase 2")
    if args.command in {"refresh", "run"}:
        return _not_implemented("phase 3")
    if args.command == "export":
        return _not_implemented("phase 5")
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
