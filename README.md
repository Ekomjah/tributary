# Tributary

![Tributary Cover Picture](./tributary.jpeg)

**A self-hosted pipe builder for your feeds, with a local model as one of the boxes.**

Tributary brings back two things people still miss: Yahoo Pipes (drag boxes to mash feeds together) and Google Reader (a calm reader with unread, stars and labels). The boxes are small, composable steps, and the app runs on your own machine.

> Status: the self-hosted build is in progress. Feed fetching, the pipe engine, the JSON API and a keyboard-first reader work today. Local-model boxes, natural-language search, read-aloud and the visual editor are next.

## What it does

- **Pipes.** Chain Fetch, Merge, Dedupe, Filter, Sort and Limit boxes. A pipe is a small JSON file you can save, share and edit by hand.
- **Reader.** Unread/read, starred, labels and filters, with keyboard shortcuts (`j`/`k` to move, `s` to star, `m` to mark read).
- **Local first.** Feeds, stars and labels live in one SQLite file. The API and reader run on your machine. No accounts.
- **Next:** local-model boxes for summaries and meaning-based filters, a natural-language search box backed by SerpAPI, read-aloud, and a visual pipe editor.

## Quick start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Node.js 20+ with [pnpm](https://pnpm.io/), and [Ollama](https://ollama.com) when the local-model boxes land.

```bash
git clone https://github.com/Ekomjah/tributary
cd tributary
cp .env.example .env
cd backend
uv sync
uv run tributary init-db
uv run tributary fetch https://hnrss.org/frontpage
uv run tributary serve
```

The API is at <http://127.0.0.1:8000>, with interactive docs at <http://127.0.0.1:8000/docs>.

Run the reader in a second terminal:

```bash
cd frontend
pnpm install
pnpm dev
```

Open <http://localhost:3000>. The reader talks to the API through `NEXT_PUBLIC_API_BASE`, which defaults to `http://127.0.0.1:8000`.

Run a pipe without the browser (from `backend/`):

```bash
uv run tributary run ../pipes/example.json
```

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

- **Engine:** Python, FastAPI, feedparser, trafilatura, SQLAlchemy, SQLite.
- **Reader:** Next.js with React. The API and reader run as two local processes during development.
- **Pipes:** JSON files. `tributary run` executes one from the CLI; the API can save and run them too.
- **Search and AI boxes:** opt-in and not implemented yet. They will use SerpAPI and Ollama respectively.

## Configuration

Copy `.env.example` to `.env`. Nothing is required for basic use.

| Variable                      | Purpose                                                          | Default                  |
| ----------------------------- | ---------------------------------------------------------------- | ------------------------ |
| `TRIBUTARY_DB_PATH`           | SQLite database file, relative to the repo root or absolute      | `tributary.db`           |
| `OLLAMA_MODEL`                | Model used by the upcoming AI boxes                              | `gemma3:1b`              |
| `OLLAMA_HOST`                 | Ollama address                                                   | `http://localhost:11434` |
| `SENTRY_DSN`                  | Sentry project DSN. Monitoring is on by default once this is set | sample in `.env.example` |
| `SENTRY_ENABLED`              | Set to `false` to opt out of Sentry                              | `true`                   |
| `SENTRY_TRACES_SAMPLE_RATE`   | Share of requests traced, from 0 to 1                            | `0.25`                   |
| `SENTRY_PROFILES_SAMPLE_RATE` | Share of traces profiled, from 0 to 1                            | `0.1`                    |
| `TRIBUTARY_FETCH_TIMEOUT`     | Seconds before a feed request times out                          | `20`                     |
| `NEXT_PUBLIC_API_BASE`        | API address used by the reader                                   | `http://127.0.0.1:8000`  |

## Privacy

- Your feeds, stars and labels stay on your machine in a local SQLite file.
- Article text is not sent to a cloud service. The upcoming AI boxes will use the local Ollama instance.
- Sentry is on by default when `SENTRY_DSN` is set; set `SENTRY_ENABLED=false` to opt out. It receives errors, traces, profiles, logs and feed metrics, but not article text, request bodies, headers, cookies, query strings, local variables or default PII.
- The future natural-language search box will be off unless a SerpAPI key is configured. It will send only the query, never article text or reading history.

## Monitoring

Sentry is enabled by default when a DSN is configured. Feed refreshes record duration, new-item counts and failures as errors and metrics. A pipe run is one trace with a span per box. Set `SENTRY_ENABLED=false` to turn all of it off.

## Deployment

The current build is self-hosted: SQLite, the API and the reader run locally. The reader is served by Next.js during development; `tributary serve` runs the API.

A read-only cloud demo is a future deployment profile, not part of this build. It will use MongoDB for storage and Auth0 for accounts, and will not run the local model. The self-hosted build stays account-free.

## Limitations

- The local-model boxes, natural-language search, read-aloud and visual editor are not implemented yet.
- The reader and API run as separate local processes during development.
- Single user, no accounts, by design for the self-hosted build.

## Development

The root `Makefile` wraps the common commands:

```bash
make setup       # install backend and frontend dependencies
make dev         # run the API and reader together
make dev-api     # API only, at http://127.0.0.1:8000
make dev-client  # reader only, at http://localhost:3000
make test-api    # backend tests
make check-api   # backend lint and tests
make check-client # frontend lint and production build
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
pnpm build
```

This project's coding sessions are recorded with [Entire](https://entire.io); the session is linked in the write-up.

## License

MIT. See [LICENSE](LICENSE).
