# Tributary backend

FastAPI engine for Tributary: SQLite storage, feed fetching, the pipe engine, and
the JSON API used by the reader and editor.

## Setup

```bash
cd backend
uv sync --group dev
uv run tributary init-db
uv run tributary serve
```

The API is at <http://127.0.0.1:8000>, with interactive docs at
<http://127.0.0.1:8000/docs>. Copy the repository-level `.env.example` to `.env`
to override defaults. The CLI is built with Typer; `uv run tributary --help` lists
every command. Sentry is enabled by default once `SENTRY_DSN` is set; set
`SENTRY_ENABLED=false` to opt out.

## Current phase

Phase 2 is complete: feed fetching with `httpx` and `feedparser`, conditional GET,
per-feed error isolation, GUID/link normalization, deduplication, trafilatura
cleaning for substantial feed HTML, and the `tributary fetch` and
`tributary refresh` commands.

Next: Phase 3 (the box engine and `tributary run`), then the API, reader, and AI
cache.

## Why a CLI?

The browser is the friendly surface; the CLI is the local control plane. It
bootstraps the database, subscribes to feeds, refreshes them, runs a pipe file,
exports training data, and starts the server without needing the frontend. That
makes unattended refreshes possible with cron or a systemd timer, keeps scripts
and tests honest, and gives the hosted editor the same engine the CLI uses. The
CLI and API call the same service layer, so there is one implementation to debug.

## Commands

```bash
uv run tributary --help
uv run tributary init-db
uv run tributary fetch https://hnrss.org/frontpage
uv run tributary refresh
uv run tributary serve
uv run pytest
uv run ruff check .
```

## Layout

```text
src/tributary/
  config.py      settings and repository paths
  db.py          engine, sessions, SQLite pragmas, UTC timestamp type
  models.py      Feed, Item, Label, Pipe, Run, BoxCache
  schemas.py     Pydantic request/response models
  main.py        FastAPI app factory
  observability.py  Sentry errors, traces, profiles, logs and metrics
  cli.py         Typer-based tributary command
  api/           route modules (added in Phase 4)
  services/      feeds.py handles fetching, parsing and deduplication
  boxes/         pipe boxes (Phase 3)
```
