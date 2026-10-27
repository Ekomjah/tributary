# Task 001 implementation plan

Alright, for starters, we: MVP database tables (SQLite)

| Table       | Key columns                                                                    | Purpose                                                                          |
| ----------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| feeds       | id, url, title, last_fetched                                                   | Subscriptions                                                                    |
| items       | id, feed_id, guid, title, link, published, content, is_read, starred, decision | One row per article. `decision` is keep/drop/null, and it is your training label |
| labels      | id, name                                                                       | Tags you create                                                                  |
| item_labels | item_id, label_id                                                              | Many-to-many tags                                                                |
| pipes       | id, name, spec_json                                                            | Saved pipes                                                                      |
| runs        | id, pipe_id, started, seconds, status                                          | Run history                                                                      |
| box_cache   | item_id, box, params_hash, output, model                                       | Cached AI results, so only new items hit the model                               |

## Core endpoints

| Endpoint                              | Does                                    |
| ------------------------------------- | --------------------------------------- |
| GET/POST /feeds                       | List or add a subscription              |
| POST /feeds/refresh                   | Fetch new items                         |
| GET /items?unread=&starred=&label=&q= | The reader list with filters            |
| PATCH /items/{id}                     | Set read, starred, decision             |
| POST /items/{id}/labels               | Add a label                             |
| GET/POST /pipes                       | List or save pipes                      |
| POST /pipes/{id}/run                  | Run a pipe, return items                |
| GET /export/training                  | Dump labelled items as JSONL for Tinker |

## Where to start

1. set up the tables above, and write the `Item` model.
2. Fetch and store one feed (`feedparser`), and print the items.
3. Build the box interface (list of items in, list out), then fetch, dedupe, sort, and filter by keyword.
4. Add the `/items` endpoints and a bare reader page.
5. Add summarize with Gemma and the cache, then start labeling items so you have training data.
6. Build the editor after the engine works from the CLI.
