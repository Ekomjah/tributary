# Tributary

![Tributary Cover Picture](./tributary.jpeg)

**A visual pipe builder for your feeds, with a local model as one of the boxes.**

Tributary brings back two things people still miss: Yahoo Pipes (drag boxes to mash feeds together) and Google Reader (a calm reader with unread, stars and labels). Here the boxes can be small local-model steps such as "summarize" or "filter by meaning", and everything runs on your own machine.

> Status: Phase 2 of the MVP is in place — backend scaffold, SQLite schema, feed fetching and the `tributary` CLI. The pipe engine, reader, AI boxes and editor are in progress. Built for the DEV Hacktoberfest Open-Source AI Challenge, Week 4. Numbers marked `TODO` are filled in from real runs before release.

## What it does

- **Pipes.** Wire boxes together on a canvas: Fetch, Merge, Dedupe, Filter by keyword, Sort, Summarize, Filter by meaning, Why you'd care, Read aloud. A pipe is a small JSON file you can save, share and edit by hand.
- **Reader.** Unread/read, starred, labels and filters, with keyboard shortcuts (`j`/`k` to move, `s` to star).
- **Learns your taste.** Your stars and skips become labels used to fine-tune the filter model.
- **Local first.** Feeds, stars and results live in one SQLite file. The AI boxes run through Ollama on your laptop. No accounts.
- **Read aloud (optional).** Turn the top items into a short spoken briefing with a tone selector. Off by default.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com).

```bash
git clone https://github.com/Ekomjah/tributary
cd tributary
ollama pull gemma3:1b
cp .env.example .env
cd backend
uv sync
uv run tributary init-db
uv run tributary serve
```

Open <http://localhost:8000>.

Run a pipe without the browser (from `backend/`):

```bash
uv run tributary run ../pipes/example.json
```

Or with Docker: `docker compose up`.

## Example pipe

```json
{
  "name": "Dependency releases, one line each",
  "steps": [
    {
      "box": "fetch",
      "urls": ["https://github.com/fastapi/fastapi/releases.atom"]
    },
    { "box": "dedupe" },
    { "box": "summarize", "style": "one line" },
    { "box": "sort", "by": "date", "order": "desc" }
  ]
}
```

Each box takes a list of items and returns a list of items, so boxes combine in any order.

## How it works

```
feeds -> [Fetch] -> [Merge] -> [Dedupe] -> [AI boxes] -> [Sort] -> reader / spoken briefing
                                               |
                                    Ollama (base or tuned model)
```

- **Engine:** Python, FastAPI, feedparser, trafilatura, SQLAlchemy, SQLite.
- **Editor and reader:** Next.js with React Flow, exported as static files and served by the engine, so one process runs everything.
- **Model:** `gemma3:1b` by default. A tuned model trained on Tinker can be swapped in with an environment variable.
- **Results are cached** per item and per box, so only new items hit the model.

## Roadmap

| Phase | Ships | Status |
| --- | --- | --- |
| 3. Box engine | JSON pipe loader, Fetch/Merge/Dedupe/Filter/Sort/Limit boxes, `tributary run` | Next |
| 4. API and reader | Feed, item, pipe and run endpoints; unread/star filters; keyboard-first reader | Planned |
| 5. AI boxes and cache | Summarize, Filter by meaning, Why you'd care; per-item cache; JSONL export | Planned |
| 6. SerpAPI search | Opt-in query box and related links; cached, rate-limited, off without a key | Planned |
| 7. Editor and demo | React Flow canvas, save/load pipes, run preview, hosted demo | Planned |

The SerpAPI box calls the REST API with the existing `httpx` client, so it adds no SDK dependency.

## Fine-tuned filter

The "Filter by meaning" and "Why you'd care" boxes can use a small open model tuned on your own stars and skips.

| Model            | Held-out accuracy | Precision on "keep" | Seconds per item |
| ---------------- | ----------------- | ------------------- | ---------------- |
| Base `gemma3:1b` | TODO              | TODO                | TODO             |
| Tuned            | TODO              | TODO                | TODO             |

Training notes and the export steps (adapter, merge, GGUF, Ollama) are in `docs/finetune.md`.

## Configuration

Copy `.env.example` to `.env`. Nothing is required for basic use.

| Variable                      | Purpose                                                          | Default                  |
| ----------------------------- | ---------------------------------------------------------------- | ------------------------ |
| `TRIBUTARY_DB_PATH`           | SQLite database file, relative to the repo root or absolute      | `tributary.db`           |
| `OLLAMA_MODEL`                | Model used by the AI boxes                                       | `gemma3:1b`              |
| `OLLAMA_HOST`                 | Ollama address                                                   | `http://localhost:11434` |
| `SENTRY_DSN`                  | Sentry project DSN. Monitoring is on by default once this is set | sample in `.env.example` |
| `SENTRY_ENABLED`              | Set to `false` to opt out of Sentry                              | `true`                   |
| `SENTRY_TRACES_SAMPLE_RATE`   | Share of requests traced, from 0 to 1                            | `0.25`                   |
| `SENTRY_PROFILES_SAMPLE_RATE` | Share of traces profiled, from 0 to 1                            | `0.1`                    |
| `TRIBUTARY_FETCH_TIMEOUT`     | Seconds before a feed request times out                          | `20`                     |
| `SERPAPI_API_KEY`             | Enable the opt-in SerpAPI search box (planned, Phase 6)          | empty (off)              |
| `ELEVENLABS_API_KEY`          | Enable cloud read-aloud (planned, not in the MVP backend yet)    | empty (off)              |

## Privacy

- Your feeds, stars and labels stay on your machine in a local SQLite file.
- Article text goes only to your local model. It is never sent to a cloud service.
- Sentry is on by default when `SENTRY_DSN` is set; set `SENTRY_ENABLED=false` to opt out. It receives errors, traces, profiles, logs and feed metrics, but not article text, request bodies, headers, cookies, query strings, local variables or default PII. ElevenLabs stays off unless you set its key, and then only the short script you are about to hear is sent. The SerpAPI search box (Phase 6) stays off without a key and sends only the query, never article text or reading history.
- Without an ElevenLabs key, read-aloud uses a local voice.

## Monitoring

Sentry is enabled by default when a DSN is configured. Feed refreshes record duration, new-item counts and failures as errors and metrics; each pipe run will be one trace with a span per box. AI spans will record the model, tokens and latency. Set `SENTRY_ENABLED=false` to turn all of it off.

## Hosted demo

A read-only demo with sample feeds and pre-computed results runs at <https://tributary.tech> (TODO: confirm domain). It can't run a local model, so use the quick start above for the real thing.

## Limitations

- A small model makes mistakes when filtering. Check the held-out numbers above before trusting it.
- On a CPU-only laptop the AI boxes are slow on a first run. Cached results make later runs fast.
- Single user, no accounts, by design.

## Development

```bash
cd backend
uv sync --group dev
uv run pytest
uv run ruff check .
```

This project's coding sessions are recorded with [Entire](https://entire.io); the session is linked in the write-up.

## License

MIT. See [LICENSE](LICENSE).
