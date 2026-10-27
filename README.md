# Tributary

**A visual pipe builder for your feeds, with a local model as one of the boxes.**

Tributary brings back two things people still miss: Yahoo Pipes (drag boxes to mash feeds together) and Google Reader (a calm reader with unread, stars and labels). Here the boxes can be small local-model steps such as "summarize" or "filter by meaning", and everything runs on your own machine.

> Status: built for the DEV Hacktoberfest Open-Source AI Challenge, Week 4. Numbers marked `TODO` are filled in from real runs before release.

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
uv sync
uv run tributary serve
```

Open <http://localhost:8000>.

Run a pipe without the browser:

```bash
uv run tributary run pipes/example.json
```

Or with Docker: `docker compose up`.

## Example pipe

```json
{
  "name": "Dependency releases, one line each",
  "steps": [
    { "box": "fetch", "urls": ["https://github.com/fastapi/fastapi/releases.atom"] },
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

- **Engine:** Python, FastAPI, feedparser, trafilatura, SQLite.
- **Editor and reader:** Next.js with React Flow, exported as static files and served by the engine, so one process runs everything.
- **Model:** `gemma3:1b` by default. A tuned model trained on Tinker can be swapped in with an environment variable.
- **Results are cached** per item and per box, so only new items hit the model.

## Fine-tuned filter

The "Filter by meaning" and "Why you'd care" boxes can use a small open model tuned on your own stars and skips.

| Model | Held-out accuracy | Precision on "keep" | Seconds per item |
| --- | --- | --- | --- |
| Base `gemma3:1b` | TODO | TODO | TODO |
| Tuned | TODO | TODO | TODO |

Training notes and the export steps (adapter, merge, GGUF, Ollama) are in `docs/finetune.md`.

## Configuration

Copy `.env.example` to `.env`. Nothing is required for basic use.

| Variable | Purpose | Default |
| --- | --- | --- |
| `OLLAMA_MODEL` | Model used by the AI boxes | `gemma3:1b` |
| `OLLAMA_HOST` | Ollama address | `http://localhost:11434` |
| `SENTRY_DSN` | Enable monitoring (opt-in) | empty (off) |
| `ELEVENLABS_API_KEY` | Enable cloud read-aloud (opt-in) | empty (off) |

## Privacy

- Your feeds, stars and labels stay on your machine in a local SQLite file.
- Article text goes only to your local model. It is never sent to a cloud service.
- Sentry and ElevenLabs are off unless you set their keys. With Sentry on, article text is redacted by default. With ElevenLabs on, only the short script you are about to hear is sent.
- Without an ElevenLabs key, read-aloud uses a local voice.

## Monitoring

With `SENTRY_DSN` set, each pipe run is one trace and each box is one span. AI spans record the model, tokens and latency, and dead feeds are captured as errors.

## Hosted demo

A read-only demo with sample feeds and pre-computed results runs at <https://tributary.tech> (TODO: confirm domain). It can't run a local model, so use the quick start above for the real thing.

## Limitations

- A small model makes mistakes when filtering. Check the held-out numbers above before trusting it.
- On a CPU-only laptop the AI boxes are slow on a first run. Cached results make later runs fast.
- Single user, no accounts, by design.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
```

This project's coding sessions are recorded with [Entire](https://entire.io); the session is linked in the write-up.

## License

TODO: choose a license (MIT is a common default).
