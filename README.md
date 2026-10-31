# Tributary

![Tributary Cover Picture](./tributary.jpeg)

**A self-hosted pipe builder for your feeds, with a local model as one of the boxes.**

Tributary brings back two things people still miss: Yahoo Pipes (drag boxes to mash feeds together) and Google Reader (a calm reader with unread, stars and labels). The boxes are small, composable steps, and the app runs on your own machine.

> Status: the self-hosted build is in progress. Feed fetching, full-text extraction, the pipe engine, local-model boxes, SerpAPI search with natural-language refinement, the visual pipe editor, the JSON API and a keyboard-first reader work today. A search form in the reader and read-aloud are next.

## What it does

- **Pipes.** Chain Fetch, Search, Merge, Dedupe, Filter, Sort, Limit and Full text boxes. Build a pipe by dragging boxes at `/pipes`, or save and share it as a small JSON file you can edit by hand.
- **Reader.** Unread/read, starred, labels and filters, with keyboard shortcuts (`j`/`k` to move, `s` to star, `m` to mark read).
- **Full text.** When a feed sends only an excerpt, Tributary fetches the article once, cleans it with trafilatura, and keeps it for offline reading.
- **Local model.** Summarize each item, filter by meaning ("keep only items about databases, drop hype") and explain why a story might matter, all through Ollama on your machine by default. Set `OLLAMA_CLOUD=true` to use Ollama Cloud instead.
- **Search.** Ask for news or web results in plain language. The local model rewrites the request into search parameters, SerpAPI runs it, and the results become a search feed in the sidebar. It is off unless you add a key.
- **Visual editor.** Drag boxes onto a canvas, wire them into a chain, preview the refined search query, then save and run the pipe without leaving the browser.
- **Local first.** Feeds, stars and labels live in one SQLite file. The API and reader run on your machine. No accounts.
- **Next:** a search form in the reader and read-aloud.

## Quick start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Node.js 20+ with [pnpm](https://pnpm.io/), and [Ollama](https://ollama.com) for the AI boxes.

```bash
git clone https://github.com/Ekomjah/tributary
cd tributary
make setup
cp .env.local.example .env.local
make dev
```

`.env.local` is optional for a basic install: the defaults use SQLite and a
local Ollama server. `make dev` applies the migrations, starts the API at
<http://127.0.0.1:8000> (docs at `/docs`), and starts the reader at
<http://localhost:3000>.

To run the API by itself with the profile loaded:

```bash
cd backend
uv run --env-file ../.env.local tributary init-db
uv run --env-file ../.env.local tributary fetch https://hnrss.org/frontpage
uv run --env-file ../.env.local tributary serve
```

The reader reads `NEXT_PUBLIC_API_BASE` from `frontend/.env.local`, not from the
root profile file. It defaults to `http://127.0.0.1:8000`.

Run a pipe without the browser (from `backend/`):

```bash
uv run tributary run ../pipes/example.json
uv run tributary run ../pipes/summarize.json
```

The summarize pipe needs Ollama running with the configured model:

```bash
ollama pull gemma3:1b
uv run tributary doctor
```

For Ollama Cloud instead, set `OLLAMA_CLOUD=true` and `OLLAMA_API_KEY` in
`.env.local`. Cloud mode uses `gemma4:3b` at `https://ollama.com` and does not
need a local model pull. `OLLAMA_CLOUD_MODEL` and `OLLAMA_CLOUD_HOST` override
those defaults.

Search needs a [SerpAPI](https://serpapi.com) key in `.env.local`:

```bash
uv run tributary search "AI regulation this week"
uv run tributary run ../pipes/search.json
```

The local model refines the request first and the command shows what will be sent. Use `--no-refine` to send your words as-is. If Ollama is unavailable, search falls back to the raw query automatically.

The visual editor lives at <http://localhost:3000/pipes>. The API must be running; save a pipe before running it, so the browser and the CLI execute the same stored spec.

`doctor` checks the database, Ollama, SerpAPI and Sentry. `tributary export --out training.jsonl` writes your Keep/Drop labels as JSONL for fine-tuning.

## Example pipe

```json
{
  "name": "Dependency releases, newest first",
  "steps": [
    {
      "box": "fetch",
      "urls": [
        "https://github.com/fastapi/fastapi/releases.atom",
        "https://github.com/encode/uvicorn/releases.atom"
      ]
    },
    { "box": "merge" },
    { "box": "dedupe", "by": "link" },
    { "box": "sort", "by": "published", "order": "desc" },
    { "box": "limit", "count": 10 }
  ]
}
```

Each box takes a list of items and returns a list of items, so boxes combine in any order.

## How it works

```text
feeds -> [Fetch] -> [Merge] -> [Dedupe] -> [Filter] -> [Sort] -> [Limit] -> reader
```

- **Engine:** Python, FastAPI, feedparser, trafilatura, SQLAlchemy, SQLite locally
  and PostgreSQL in the cloud.
- **Reader:** Next.js with React. The API and reader run as two local processes during development.
- **Pipes:** JSON files. `tributary run` executes one from the CLI; the API saves and runs them, and the React Flow editor at `/pipes` writes the same spec.
- **AI boxes:** Summarize, Filter by meaning and Why you'd care call Ollama and cache each answer in the database. The default is the local Ollama instance; cloud mode sends prompts to Ollama Cloud instead.
- **Search:** the Search box and `tributary search` ask Ollama to refine the request, call SerpAPI, then store the results under a virtual `search://` feed. Those feeds appear under **Searches** in the sidebar and stay out of All items, Unread and Starred. A search is cached for six hours.

## Configuration

Copy the self-hosted template to `.env.local` and edit it as needed:

```bash
cp .env.local.example .env.local
```

Nothing is required for basic local use: SQLite and local Ollama are the
defaults. `.env.example` is the full reference for every switch, including the
Sentry categories. The generated `.env.local` is git-ignored.

Load the file explicitly when you run a command outside the Makefile:

```bash
cd backend
uv run --env-file ../.env.local tributary serve
```

`uv run --env-file` sets process environment variables, which take precedence
over the `.env` files the app loads on its own.

### Self-hosted profile

Leave `DEV_ENV` empty. The build is account-free: no Auth0, no per-user
libraries. Set `DATABASE_URL` if you want PostgreSQL instead of SQLite. The
reader does not use `.env.local`; set `NEXT_PUBLIC_API_BASE` in
`frontend/.env.local`.

### Ollama modes

Local Ollama is the default. Set `OLLAMA_CLOUD=true` and `OLLAMA_API_KEY` to
send AI calls to Ollama Cloud at `https://ollama.com` with `gemma4:3b`.
`OLLAMA_MODEL` and `OLLAMA_HOST` apply only to local mode; use
`OLLAMA_CLOUD_MODEL` and `OLLAMA_CLOUD_HOST` to change the cloud defaults. If
your account exposes the model under a different tag, set
`OLLAMA_CLOUD_MODEL` to that exact tag. The app refuses to start in cloud mode
without a key, and `doctor` explains what is missing.

### Storage

SQLite remains the default storage. Set `DATABASE_URL` to run the same
account-free build on PostgreSQL. `postgres://` and `postgresql://` URLs are
normalized to SQLAlchemy's psycopg driver. `DATABASE=postgres` is an optional
selector that makes a missing `DATABASE_URL` fail at startup instead of silently
creating a SQLite file. Schema changes are applied with Alembic automatically at
startup; `uv run tributary init-db` runs the same migrations by hand.

For local PostgreSQL, the repository ships disposable-container targets that
use `postgres:16-alpine` on port 55432:

```bash
make pg-start            # start the disposable database
make db-init-postgres    # apply migrations to it
make test-api-postgres   # run the full backend suite against it
make pg-stop             # stop and remove it
```

PostgreSQL pool sizing and idle-connection recovery are controlled by
`DATABASE_POOL_*` and `DATABASE_CONNECT_TIMEOUT`.

| Variable                         | Purpose                                                          | Default                  |
| -------------------------------- | ---------------------------------------------------------------- | ------------------------ |
| `DEV_ENV`                        | Leave empty for the self-hosted build                            | empty                    |
| `TRIBUTARY_DB_PATH`              | SQLite database file, relative to the repo root or absolute      | `tributary.db`           |
| `DATABASE`                       | Optional selector: `sqlite` or `postgres`; empty infers from URL | empty (SQLite)           |
| `DATABASE_URL`                   | PostgreSQL or SQLite URL; overrides `TRIBUTARY_DB_PATH`          | unset                    |
| `MIGRATION_DATABASE_URL`         | Explicit override for the DDL/migration URL                      | unset                    |
| `DATABASE_POOL_SIZE`             | PostgreSQL pool size per process                                 | `5`                      |
| `DATABASE_MAX_OVERFLOW`          | Extra PostgreSQL connections above the pool size                 | `5`                      |
| `DATABASE_POOL_TIMEOUT`          | Seconds to wait for a pooled connection                          | `30`                     |
| `DATABASE_POOL_RECYCLE`          | Seconds before a pooled connection is replaced                   | `300`                    |
| `DATABASE_CONNECT_TIMEOUT`       | Seconds before a PostgreSQL connect attempt fails                | `10`                     |
| `OLLAMA_CLOUD`                   | Use Ollama Cloud instead of the local Ollama server              | `false`                  |
| `OLLAMA_API_KEY`                 | Ollama Cloud API key; required when `OLLAMA_CLOUD=true`          | unset                    |
| `OLLAMA_CLOUD_MODEL`             | Model used in cloud mode                                         | `gemma4:3b`              |
| `OLLAMA_CLOUD_HOST`              | Cloud mode endpoint                                              | `https://ollama.com`     |
| `OLLAMA_MODEL`                   | Model used by the AI boxes in local mode                         | `gemma3:1b`              |
| `OLLAMA_HOST`                    | Local Ollama address                                             | `http://localhost:11434` |
| `OLLAMA_TIMEOUT`                 | Seconds before a model call times out                            | `120`                    |
| `SERPAPI_API_KEY`                | SerpAPI key. Search is off when empty                            | unset                    |
| `SERPAPI_ENGINE`                 | Default search engine: `google_news` or `google`                 | `google_news`            |
| `SERPAPI_MAX_RESULTS`            | Results per search, 1 to 20                                      | `10`                     |
| `SERPAPI_CACHE_TTL`              | Seconds a search result stays cached                             | `21600`                  |
| `SERPAPI_TIMEOUT`                | Seconds before a SerpAPI request times out                       | `20`                     |
| `SENTRY_DSN`                     | Sentry project DSN. Leave empty to run without Sentry or tracing | unset (opt-in)           |
| `SENTRY_ENABLED`                 | Hard opt-out; a DSN alone enables Sentry                         | `true`                   |
| `SENTRY_TRACES_SAMPLE_RATE`      | Share of requests traced, from 0 to 1; 0 keeps errors on         | `0.25`                   |
| `SENTRY_PROFILES_SAMPLE_RATE`    | Share of traces profiled, from 0 to 1                            | `0.1`                    |
| `SENTRY_COLLECT_GEN_AI`          | Capture model prompts and responses in GenAI spans               | `true`                   |
| `SENTRY_COLLECT_HTTP_BODIES`     | Capture request and response bodies                              | `true`                   |
| `SENTRY_MAX_REQUEST_BODY_SIZE`   | Body cap: `never`, `small`, `medium` or `always`                 | `medium`                 |
| `SENTRY_COLLECT_STACK_VARIABLES` | Capture local variables in stack frames                          | `true`                   |
| `TRIBUTARY_FETCH_TIMEOUT`        | Seconds before a feed request times out                          | `20`                     |
| `NEXT_PUBLIC_API_BASE`           | API address used by the reader                                   | `http://127.0.0.1:8000`  |

The rest of the Sentry switches (`SENTRY_SEND_USER_INFO`,
`SENTRY_COLLECT_HTTP_HEADERS`, `SENTRY_COLLECT_QUERY_PARAMS`,
`SENTRY_COLLECT_DB_QUERIES`, `SENTRY_FRAME_CONTEXT_LINES`) are documented in
`.env.example`.

## Privacy

- In the default local profile, your feeds, stars and labels stay on your machine in a local SQLite file.
- When a feed only sends an excerpt, Tributary fetches the article page directly from the publisher, from your machine, the first time you open that item. The request carries Tributary's User-Agent and no account, cookies or reading history. The page is cleaned to text and cached in your local database.
- In local mode (the default), article text is not sent to a cloud service. The AI boxes use the local Ollama instance, and only extracted article text is sent to it. In cloud mode (`OLLAMA_CLOUD=true`), extracted article text and prompts are sent to Ollama Cloud instead.
- Sentry is opt-in through `SENTRY_DSN`. Without a DSN no Sentry client is initialized and no errors, traces, logs or metrics leave the process. With a DSN it receives errors, traces, profiles, logs, feed metrics and GenAI spans; set `SENTRY_ENABLED=false` for a hard opt-out. With the monitoring defaults it also receives request bodies, headers, database query data, stack variables and model prompts/responses; cookies, GraphQL and queues stay off. API keys and URL query strings are redacted, and every category can be turned off with the `SENTRY_COLLECT_*` switches.
- The Search box is off unless `SERPAPI_API_KEY` is configured. When it runs, your request is refined by the configured Ollama instance (local or cloud), then only the refined query, engine, locale and freshness go to SerpAPI, never article text or reading history. Results are stored in your local database and cached for six hours.

## Monitoring

Sentry is opt-in through `SENTRY_DSN`. Without a DSN the app runs without a Sentry client, so no errors, traces, logs, metrics or GenAI spans are sent. With a DSN, feed refreshes record duration, new-item counts and failures as errors and metrics. Search records request, cache-hit and error counts plus latency; API keys and URL query strings are redacted from every event. A pipe run is one trace with a span per box. AI boxes and query refinement emit `gen_ai.chat` spans with the model, token counts and, when `SENTRY_COLLECT_GEN_AI=true`, the prompts and responses. `SENTRY_TRACES_SAMPLE_RATE=0` keeps error reporting on while turning tracing off; `SENTRY_ENABLED=false` turns all of it off.

## Self-hosting

The build stays account-free: SQLite by default, or PostgreSQL when
`DATABASE_URL` is set. `tributary serve` runs the API and applies migrations on
startup. The reader is a Next.js app:

```bash
cd backend
uv run tributary serve --host 0.0.0.0 --port 8000

cd ../frontend
pnpm build
pnpm start
```

Point the reader at the API with `NEXT_PUBLIC_API_BASE` before building. Keep
`.env.local`, the SQLite database and the reader's `.next` directory off any
public path.

## Limitations

- A search form in the reader and read-aloud are not implemented yet. Search works through the API, the CLI, the Search pipe box and the editor's query preview.
- The reader and API run as separate local processes during development.
- The build is single-user with no accounts. Keep it on your own machine or
  behind your own access control.

## Development

The root `Makefile` wraps the common commands:

```bash
make setup       # install backend and frontend dependencies
make dev         # run the API (local SQLite) and reader together
make dev-api     # API only, local SQLite, at http://127.0.0.1:8000
make dev-api-postgres # API against the disposable PostgreSQL database
make dev-client  # reader only, at http://localhost:3000
make test-api    # backend tests (SQLite)
make test-api-postgres # backend tests against postgres:16-alpine
make pg-stop     # stop the disposable PostgreSQL container
make check-api   # backend lint and tests
make test-client # frontend Vitest suite
make check-client # frontend lint, tests and production build
make ci          # everything CI runs
```

Run `make help` for the full list. The underlying commands are:

```bash
cd backend
uv sync --group dev
uv run pytest
uv run ruff check .

cd ../frontend
pnpm lint
pnpm test
pnpm build
```

This project's coding sessions are recorded with [Entire](https://entire.io); the session is linked in the write-up.

## License

MIT. See [LICENSE](LICENSE).
