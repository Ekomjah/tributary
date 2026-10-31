# Tributary backend

FastAPI engine for Tributary: SQLite or PostgreSQL storage, feed fetching, the
pipe engine, and the JSON API used by the reader and editor.

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
`SENTRY_ENABLED=false` to opt out. Monitoring captures request data, stack
variables and GenAI prompts/responses by default; each category has a
`SENTRY_COLLECT_*` switch, and authorization/cookie headers plus known secrets
are redacted.

SQLite is the default. Set `DATABASE_URL` to a PostgreSQL URL to use Postgres
instead; Render's `postgres://` form is normalized automatically. `DATABASE=postgres`
makes a missing URL a startup error. On Neon, keep the pooled URL in
`DATABASE_URL` and let `DATABASE_URL_UNPOOLED` (written by `neon env pull`) drive
migrations, or set `MIGRATION_DATABASE_URL` explicitly. Schema changes live in
`migrations/` and run through Alembic at startup or with
`uv run tributary init-db`. Set `DEV_ENV` to a non-empty value only when the
PostgreSQL, Auth0 and CORS settings for the cloud profile are present.

The reader is a separate Next.js app in `../frontend`. Run it with `pnpm dev`.

## Status

Feed fetching with `httpx` and `feedparser`, conditional GET, per-feed error
isolation, GUID/link normalization, deduplication, trafilatura cleaning, the pipe
engine, local-model boxes with caching, SerpAPI search with natural-language
refinement, the JSON API, and the CLI are in place. The visual pipe editor lives
in the Next.js app at `/pipes`.

Search and AI boxes are opt-in; the self-hosted build needs no account.

## Why a CLI?

The browser is the friendly surface; the CLI is the local control plane. It
bootstraps the database, subscribes to feeds, refreshes them, runs a pipe file,
exports training data, and starts the server without needing the frontend. That
makes unattended refreshes possible with cron or a systemd timer, keeps scripts
and tests honest, and gives the API the same engine the CLI uses. The CLI and API
call the same service layer, so there is one implementation to debug.

## Commands

```bash
uv run tributary --help
uv run tributary init-db
uv run tributary fetch https://hnrss.org/frontpage
uv run tributary refresh
uv run tributary run ../pipes/example.json
uv run tributary search "AI regulation this week"
uv run tributary serve
uv run pytest
uv run ruff check .
```

## Layout

```text
src/tributary/
  config.py      settings, local/cloud profile and repository paths
  db.py          engine, sessions, migrations, UTC timestamp type
  models.py      Feed, Item, Label, Pipe, Run, BoxCache, SearchCache
  schemas.py     Pydantic request/response models
  main.py        FastAPI app factory
  observability.py  Sentry errors, traces, profiles, logs and metrics
  cli.py         Typer-based tributary command
  api/           feeds, items, labels, pipes, runs, search and refine routes
  services/      feeds, search, refine, model and cache services
  boxes/         pipe specification, plain and AI boxes, search and the runner
```
