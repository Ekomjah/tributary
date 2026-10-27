# Tributary: MVP plan

Tributary is a visual pipe builder for news feeds where a local, fine-tuned model is one of the boxes, with a plain reader and a read-aloud briefing at the end. Built for Hacktoberfest Week 4, due Oct 31.

## What RSS is

Most blogs, news sites, podcasts, YouTube channels and GitHub release pages publish a machine-readable list of their latest posts at a URL, usually ending in `/feed`, `/rss` or `.xml`. That list is an RSS (or GUEST_ACTIONAtom) feed. Each item has a title, link, date and summary or full text. A feed reader checks many of these URLs for you and shows everything in one place, with no algorithm deciding what you see and no account needed.

You can try it by opening `https://hnrss.org/frontpage` in a browser. That is the Hacker News front page as a feed. In Python, the `feedparser` library turns a feed URL into a plain list of items in one call.

## What the two old tools did

**Google Reader** (shut down in 2013) was the best-loved feed reader. It had a clean unread list, folders, stars, keyboard shortcuts and sharing. People still miss it because it was fast and calm and it respected the order you chose. Nothing replaced it exactly, which is why "reborn" works as a pitch.

**Yahoo Pipes** (shut down in 2015) was a visual programming tool. You dragged boxes onto a canvas and wired them together: "Fetch feed A" and "Fetch feed B" went into "Merge", then "Filter: title contains Python", then "Sort by date", then "Output as feed". The result was a new feed with its own URL. Non-programmers built custom news streams that way.

## The key insight: they are one project

Reader is where feeds get read. Pipes is how a feed gets shaped before reading. Together you get a reader whose feeds you can program visually, with local models as some of the boxes. The pipe is the star and the reader is just where the output lands.

## Name and domain

**Tributary**: many small feeds flowing into one stream. Target domain: `tributary.tech` (claim the free .tech code at hacktoberfest.com/my/promos; if taken, try `readtributary.tech`).

## The stack

| Layer | Choice | Job |
| --- | --- | --- |
| Editor UI | Next.js + React Flow | Drag boxes, wire them into a pipe |
| Engine and API | Python, FastAPI | Run pipes, serve the reader |
| Feed fetching | feedparser, trafilatura | Read feeds, extract clean article text |
| Storage | SQLite | Items, stars, labels, cached box results |
| Base model | gemma3:1b through Ollama | Summarize and filter before tuning |
| Tuned model | Small open model, LoRA-tuned on Tinker | Filter by meaning, "why you'd care" |
| Voice | ElevenLabs API (opt-in) | Read the briefing aloud, selectable tone |
| Monitoring | Sentry Agent Tracing | One trace per pipe run, one span per box |
| Dev context | Entire | Checkpoints of the coding-agent sessions |
| Hosting | Render + .tech domain | Hosted editor and demo mode |

## What to build (MVP)

**Pipe engine (the star)**

- A pipe is a small JSON file listing steps, so you can save, share and edit it as plain text.
- Box types: Fetch, Merge, Dedupe, Filter by keyword, Sort, Read aloud, and the AI boxes.
- AI boxes: Summarize (one line), Filter by meaning ("keep only items about X, drop hype"), and Why you'd care (learned from your stars). Cluster is a later add.
- Each box takes a list of items and returns a list of items, which keeps the engine easy to write and test.

**Visual editor:** a React Flow canvas with drag-to-connect nodes. This is what a judge sees in a screenshot.

**Reader view:** a plain list with unread, star and keyboard shortcuts (j/k to move, s to star). Stars and skips double as training labels.

## Fine-tuning plan (Tinker)

Filtering and "why you'd care" are judgments about your taste, so tuning on your own stars is the honest reason to fine-tune.

1. Collect 300 to 500 items and label them keep or drop (the reader's star and skip do this; hand-label 100 first).
2. Split 70/15/15 into train, validation and a held-out test set you never tune on.
3. Train a LoRA adapter on Tinker on a small open model.
4. Download the adapter, merge it, convert to GGUF and load it in Ollama.
5. Compare base and tuned on the held-out set: accuracy, precision on "keep", seconds per item.

**Check on day 1:** that Tinker's supported models include one small enough (about 1B to 3B) for your 8 GB CPU laptop, and that the export-to-Ollama path works. If not, fall back to a prompt-only Filter box with the same eval, and drop the Tinker claim in the post. Only claim the Tinker category if the tuned model measurably beats the base.

## Read aloud (ElevenLabs)

A "Read aloud" output box turns the top items' one-line summaries into a short script and sends it to ElevenLabs. A tone selector (Calm, Briefing, Upbeat) maps to a voice, its voice settings and a script-style instruction given to the local model. It is off by default and sends only the short script, never full articles.

ElevenLabs is a closed cloud service, so it is not part of the open core. Add a local fallback voice (such as Piper) so the app still speaks offline, and use this in the write-up's "where a closed model is better" section.

## Monitoring (Sentry)

Each pipe run is one trace and each box is one span. AI spans record model name, tokens and latency; dead feeds are captured as errors; article text is redacted by default. Use the real findings in the post: slowest box, base vs tuned latency, failure rate.

## Dev context (Entire)

Run `entire enable` in the repo on day 1. It records your coding-agent sessions as checkpoints, so it documents how the project was built, not how the app behaves at runtime. Inspect the checkpoints for secrets before pushing, then link the session in the post.

## Hosting

Free hosting cannot run a local model, so the app is split in two:

- **Hosted at tributary.tech (Render):** the editor and a demo mode with sample feeds and pre-computed box results.
- **Local:** `docker compose up` (or `pip install`) runs the real engine and Ollama. The hosted editor can connect to your local engine; test the browser's localhost rules and Ollama's `OLLAMA_ORIGINS` setting early.

## Build order (Oct 27 to 31)

| Day | Work | Done when |
| --- | --- | --- |
| Oct 27 | Repo, Entire on, engine + CLI, four plain boxes, Sentry init, check Tinker's model list | `tributary run pipe.json` prints merged items |
| Oct 28 | AI boxes on gemma3:1b, SQLite cache, reader with stars, start labelling | Reader shows summarized items |
| Oct 29 | Fine-tune on Tinker, eval base vs tuned | A table of accuracy and speed exists |
| Oct 30 | Editor wired to the engine, Read aloud box, hosted demo on the domain | A pipe built by dragging runs in the browser |
| Oct 31 | Screenshots, Sentry trace, write-up, submit | Post published before the deadline |

Confirm the exact deadline hour on the challenge page. Last week's was 11:59 PM PDT, which is 7:59 AM the next day in Lagos.

## Honest risks

- **Crowding.** "RSS plus local summaries" is common. The visual pipe builder with a model you tuned on your own taste is what is different, so lead with that and keep the reader plain.
- **Tinker export.** If the tuned model cannot run on your laptop, you cannot show it working locally. Check this on day 1.
- **A small model on filtering.** It may be wrong often. The held-out eval, with base and tuned side by side, is the proof either way.
- **Too many partners.** Each tool must do one real job (Tinker tunes, Sentry traces, ElevenLabs speaks, Entire records the build). If one slips, cut it from the post rather than claim it.
- **Speed.** Show seconds per item and say plainly that a CPU-only laptop is slow.

## Use after the event

Point it at feeds you really read: Hacker News, a few blogs, GitHub release feeds for your dependencies, job boards. Build pipes such as "new releases of my dependencies, one line each".

