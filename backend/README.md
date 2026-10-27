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
to override defaults.

## Current phase

Phase 1 is complete: application settings, SQLite engine/session handling, the
seven MVP tables, a health endpoint, and the `tributary` CLI scaffold.

Next: Phase 2 (feed fetching and `tributary fetch`), then the box engine, API,
reader, and AI cache.

## Commands

```bash
uv run tributary --help
uv run tributary init-db
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
  cli.py         tributary command
  api/           route modules (added in Phase 4)
  services/      feed fetching and pipe execution (Phases 2-5)
  boxes/         pipe boxes (Phase 3)
```
