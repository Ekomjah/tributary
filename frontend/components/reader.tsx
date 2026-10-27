"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";

import { api, ApiError } from "@/lib/api";
import {
  excerpt,
  formatFullDate,
  formatRelative,
  hostOf,
  htmlToText,
  readingMinutes,
} from "@/lib/text";
import type {
  Decision,
  Feed,
  Item,
  ItemUpdate,
  ItemView,
  Label,
} from "@/lib/types";

import {
  CheckIcon,
  ExternalIcon,
  RefreshIcon,
  SearchIcon,
  SparkIcon,
  StarIcon,
  StreamIcon,
  TributaryMark,
} from "./icons";

const VIEWS: ItemView[] = ["unread", "all", "starred"];
const VIEW_NAMES: Record<ItemView, string> = {
  unread: "Unread",
  all: "All items",
  starred: "Starred",
};
const VIEW_KEYS: Record<ItemView, string> = {
  unread: "1",
  all: "2",
  starred: "3",
};
const PAGE_SIZE = 100;

interface Toast {
  message: string;
  error?: boolean;
}

function withScheme(value: string): string {
  return /^https?:\/\//i.test(value) ? value : `https://${value}`;
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export default function Reader() {
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [feeds, setFeeds] = useState<Feed[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [view, setView] = useState<ItemView>("unread");
  const [feedId, setFeedId] = useState<number | null>(null);
  const [label, setLabel] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [feedUrl, setFeedUrl] = useState("");
  const [addingFeed, setAddingFeed] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [addingLabel, setAddingLabel] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [sourcesToken, setSourcesToken] = useState(0);

  const searchRef = useRef<HTMLInputElement>(null);
  const readingRef = useRef<HTMLElement>(null);

  const showToast = useCallback((message: string, error = false) => {
    setToast({ message, error });
  }, []);

  const showError = useCallback(
    (error: unknown) => {
      let message = "Something went wrong.";
      if (error instanceof ApiError) {
        message = error.message;
      } else if (error instanceof Error) {
        message = error.message;
      }
      showToast(message, true);
    },
    [showToast],
  );

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api.listFeeds(controller.signal),
      api.listLabels(controller.signal),
    ])
      .then(([nextFeeds, nextLabels]) => {
        if (controller.signal.aborted) {
          return;
        }
        setFeeds(nextFeeds);
        setLabels(nextLabels);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          showError(error);
        }
      });

    return () => controller.abort();
  }, [showError, sourcesToken]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim());
    }, 280);
    return () => window.clearTimeout(timer);
  }, [search]);

  const scopeKey = `${view}|${feedId ?? ""}|${label ?? ""}|${query}|${reloadToken}`;
  const loading = loadedScope !== scopeKey;

  useEffect(() => {
    const controller = new AbortController();

    api
      .listItems({
        unread: view === "unread" ? true : undefined,
        starred: view === "starred" ? true : undefined,
        feedId,
        label,
        q: query || undefined,
        limit: PAGE_SIZE,
        signal: controller.signal,
      })
      .then((page) => {
        if (controller.signal.aborted) {
          return;
        }
        setItems(page.items);
        setTotal(page.total);
        setSelectedId((current) =>
          current !== null && page.items.some((item) => item.id === current)
            ? current
            : (page.items[0]?.id ?? null),
        );
        setLoadedScope(scopeKey);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        showError(error);
        setItems([]);
        setTotal(0);
        setSelectedId(null);
        setLoadedScope(scopeKey);
      });

    return () => controller.abort();
  }, [feedId, label, query, reloadToken, scopeKey, showError, view]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(
      () => setToast(null),
      toast.error ? 6500 : 3800,
    );
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    readingRef.current?.scrollTo({ top: 0 });
  }, [selectedId]);

  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) ?? null,
    [items, selectedId],
  );

  const feedNames = useMemo(() => {
    const names = new Map<number, string>();
    for (const feed of feeds) {
      names.set(feed.id, feed.title || hostOf(feed.url));
    }
    return names;
  }, [feeds]);

  const activeFeed = useMemo(
    () => (feedId === null ? null : (feeds.find((feed) => feed.id === feedId) ?? null)),
    [feedId, feeds],
  );

  const readingBody = useMemo(
    () => htmlToText(selected?.content ?? ""),
    [selected?.content],
  );
  const readingTime = useMemo(() => readingMinutes(readingBody), [readingBody]);

  const patchItem = useCallback(
    async (item: Item, patch: ItemUpdate) => {
      try {
        const updated = await api.updateItem(item.id, patch);
        setItems((current) =>
          current.map((row) => (row.id === updated.id ? updated : row)),
        );

        if (view === "unread" && typeof patch.is_read === "boolean") {
          setTotal((current) =>
            Math.max(0, current + (patch.is_read ? -1 : 1)),
          );
        }
        if (
          view === "starred" &&
          typeof patch.starred === "boolean" &&
          !patch.starred
        ) {
          setTotal((current) => Math.max(0, current - 1));
        }
      } catch (error) {
        showError(error);
      }
    },
    [showError, view],
  );

  const toggleRead = useCallback(
    (item: Item) => {
      void patchItem(item, { is_read: !item.is_read });
    },
    [patchItem],
  );

  const toggleStar = useCallback(
    (item: Item) => {
      void patchItem(item, { starred: !item.starred });
    },
    [patchItem],
  );

  const toggleDecision = useCallback(
    (item: Item, decision: Decision) => {
      void patchItem(item, {
        decision: item.decision === decision ? null : decision,
      });
    },
    [patchItem],
  );

  const openItem = useCallback(
    (item: Item) => {
      setSelectedId(item.id);
      if (!item.is_read) {
        void patchItem(item, { is_read: true });
      }
    },
    [patchItem],
  );

  const toggleLabel = useCallback(
    async (item: Item, target: Label) => {
      const attached = item.labels.some((entry) => entry.id === target.id);
      try {
        if (attached) {
          await api.removeItemLabel(item.id, target.id);
          setItems((current) =>
            current.map((row) =>
              row.id === item.id
                ? {
                    ...row,
                    labels: row.labels.filter((entry) => entry.id !== target.id),
                  }
                : row,
            ),
          );
        } else {
          const updated = await api.addItemLabel(item.id, target.id);
          setItems((current) =>
            current.map((row) => (row.id === updated.id ? updated : row)),
          );
        }
      } catch (error) {
        showError(error);
      }
    },
    [showError],
  );

  const refreshAll = useCallback(async () => {
    if (refreshing) {
      return;
    }
    setRefreshing(true);
    try {
      const results = await api.refreshFeeds();
      if (results.length === 0) {
        showToast("Add a feed first, then refresh.");
        return;
      }

      const newItems = results.reduce((sum, result) => sum + result.new_items, 0);
      const failures = results.filter((result) => result.error);
      if (failures.length > 0) {
        showToast(
          `${plural(newItems, "new item")} · ${plural(failures.length, "feed")} failed.`,
          true,
        );
      } else {
        showToast(
          `${plural(newItems, "new item")} from ${plural(results.length, "feed")}.`,
        );
      }
      setSourcesToken((current) => current + 1);
      setReloadToken((current) => current + 1);
    } catch (error) {
      showError(error);
    } finally {
      setRefreshing(false);
    }
  }, [refreshing, showError, showToast]);

  const submitFeed = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const raw = feedUrl.trim();
      if (!raw || addingFeed) {
        return;
      }

      setAddingFeed(true);
      try {
        const feed = await api.createFeed(withScheme(raw));
        setFeedUrl("");
        setFeeds((current) =>
          [...current, feed].sort((left, right) =>
            (left.title || left.url).localeCompare(right.title || right.url),
          ),
        );
        const result = await api.refreshFeed(feed.id);
        if (result.error) {
          showToast(
            `Added the feed, but the first fetch failed: ${result.error}`,
            true,
          );
        } else {
          showToast(
            `${result.title || hostOf(feed.url)}: ${plural(result.new_items, "new item")}.`,
          );
        }
        setSourcesToken((current) => current + 1);
        setReloadToken((current) => current + 1);
      } catch (error) {
        showError(error);
      } finally {
        setAddingFeed(false);
      }
    },
    [addingFeed, feedUrl, showError, showToast],
  );

  const submitLabel = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const name = newLabel.trim();
      if (!name || addingLabel) {
        return;
      }

      setAddingLabel(true);
      try {
        const created = await api.createLabel(name);
        setLabels((current) =>
          [...current, created].sort((left, right) =>
            left.name.localeCompare(right.name),
          ),
        );
        setNewLabel("");
        showToast(`Label “${created.name}” added.`);
      } catch (error) {
        showError(error);
      } finally {
        setAddingLabel(false);
      }
    },
    [addingLabel, newLabel, showError, showToast],
  );

  const moveSelection = useCallback(
    (step: number) => {
      if (items.length === 0) {
        return;
      }

      const current = items.findIndex((item) => item.id === selectedId);
      const nextIndex =
        current === -1
          ? 0
          : Math.min(items.length - 1, Math.max(0, current + step));
      const next = items[nextIndex];
      setSelectedId(next.id);
      window.requestAnimationFrame(() => {
        document
          .getElementById(`item-${next.id}`)
          ?.scrollIntoView({ block: "nearest" });
      });
    },
    [items, selectedId],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        if (event.key === "Escape") {
          target.blur();
        }
        return;
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      const key = event.key.toLowerCase();
      if (key === "/") {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (key === "1") {
        setView("unread");
        return;
      }
      if (key === "2") {
        setView("all");
        return;
      }
      if (key === "3") {
        setView("starred");
        return;
      }
      if (key === "r") {
        event.preventDefault();
        void refreshAll();
        return;
      }
      if (key === "j") {
        event.preventDefault();
        moveSelection(1);
        return;
      }
      if (key === "k") {
        event.preventDefault();
        moveSelection(-1);
        return;
      }
      if (!selected) {
        return;
      }
      if (key === "s") {
        event.preventDefault();
        void patchItem(selected, { starred: !selected.starred });
        return;
      }
      if (key === "m") {
        event.preventDefault();
        void patchItem(selected, { is_read: !selected.is_read });
        return;
      }
      if (key === "enter" && selected.link) {
        event.preventDefault();
        window.open(selected.link, "_blank", "noopener,noreferrer");
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [moveSelection, patchItem, refreshAll, selected]);

  const hasFilters = Boolean(query || label || feedId !== null);
  const heading = query
    ? "Search"
    : label
      ? label
      : activeFeed
        ? activeFeed.title || hostOf(activeFeed.url)
        : VIEW_NAMES[view];
  const eyebrow = query
    ? `Results for “${query}”`
    : label
      ? "Label"
      : activeFeed
        ? "Feed"
        : "Stream";
  const emptyTitle =
    feeds.length === 0 && !hasFilters
      ? "Start with a feed"
      : view === "unread" && !hasFilters
        ? "You’re all caught up"
        : "Nothing here yet";
  const emptyBody =
    feeds.length === 0
      ? "Paste any RSS or Atom URL in the sidebar. Tributary stores it locally and never asks for an account."
      : query
        ? `No stored items match “${query}”. Try a broader word or refresh the feeds.`
        : view === "starred"
          ? "Star an item and it will wait for you here."
          : "Refresh the feeds or change the filter to see more.";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <TributaryMark />
          </span>
          <div>
            <p className="wordmark">Tributary</p>
            <div className="brand-sub">Local feed reader</div>
          </div>
        </div>

        <div className="topbar-actions">
          <button
            type="button"
            className="ghost-button mobile-filter-button"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-expanded={sidebarOpen}
            aria-controls="reader-sidebar"
          >
            <StreamIcon />
            {sidebarOpen ? "Close" : "Browse"}
          </button>

          <form
            className="search-form"
            role="search"
            onSubmit={(event) => event.preventDefault()}
          >
            <SearchIcon />
            <input
              ref={searchRef}
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search the stream"
              aria-label="Search items"
              spellCheck={false}
            />
            {search && (
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setQuery("");
                  searchRef.current?.focus();
                }}
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </form>

          <div className="stream-count" aria-live="polite">
            <strong>{total}</strong>
            <span>
              {view === "unread"
                ? "unread"
                : view === "starred"
                  ? "starred"
                  : "in view"}
            </span>
          </div>

          <button
            type="button"
            className="ghost-button"
            onClick={() => void refreshAll()}
            disabled={refreshing}
          >
            <RefreshIcon className={refreshing ? "spin" : undefined} />
            {refreshing ? "Refreshing" : "Refresh"}
          </button>
        </div>
      </header>

      <main className="reader-grid">
        <aside
          id="reader-sidebar"
          className={`sidebar ${sidebarOpen ? "open" : ""}`}
        >
          <section className="panel nav-panel" aria-label="Views">
            <p className="eyebrow">Views</p>
            <div className="filter-list">
              {VIEWS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`filter-button ${view === option ? "active" : ""}`}
                  onClick={() => {
                    setView(option);
                    setSidebarOpen(false);
                  }}
                  aria-pressed={view === option}
                >
                  <span>{VIEW_NAMES[option]}</span>
                  <span className="filter-key">{VIEW_KEYS[option]}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="panel feed-panel" aria-label="Feeds">
            <div className="panel-head">
              <p className="eyebrow">Feeds</p>
              <span className="count">{feeds.length}</span>
            </div>

            <div className="feed-list">
              <button
                type="button"
                className={`feed-button ${feedId === null ? "active" : ""}`}
                onClick={() => {
                  setFeedId(null);
                  setSidebarOpen(false);
                }}
              >
                <span className="feed-name">All feeds</span>
                <span className="count">{feeds.length}</span>
              </button>

              {feeds.map((feed) => (
                <button
                  key={feed.id}
                  type="button"
                  className={`feed-button ${feedId === feed.id ? "active" : ""}`}
                  onClick={() => {
                    setFeedId(feed.id);
                    setSidebarOpen(false);
                  }}
                  title={feed.url}
                >
                  <span className="feed-name">
                    {feed.title || hostOf(feed.url)}
                  </span>
                  {feed.last_error && (
                    <span
                      className="feed-error"
                      title={feed.last_error}
                      aria-label="The last refresh failed"
                    >
                      !
                    </span>
                  )}
                </button>
              ))}

              {feeds.length === 0 && (
                <p className="muted small">No feeds yet. Add one below.</p>
              )}
            </div>

            <form className="add-feed" onSubmit={submitFeed}>
              <label className="sr-only" htmlFor="feed-url">
                Feed URL
              </label>
              <input
                id="feed-url"
                type="text"
                inputMode="url"
                value={feedUrl}
                onChange={(event) => setFeedUrl(event.target.value)}
                placeholder="https://hnrss.org/frontpage"
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="submit"
                className="primary-button"
                disabled={addingFeed || !feedUrl.trim()}
              >
                {addingFeed ? "Adding…" : "Add feed"}
              </button>
            </form>
          </section>

          <section className="panel label-panel" aria-label="Labels">
            <div className="panel-head">
              <p className="eyebrow">Labels</p>
              <span className="count">{labels.length}</span>
            </div>

            <div className="label-cloud">
              {labels.length === 0 ? (
                <span className="muted small">No labels yet.</span>
              ) : (
                labels.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={`label-chip ${label === entry.name ? "active" : ""}`}
                    onClick={() => {
                      setLabel((current) =>
                        current === entry.name ? null : entry.name,
                      );
                      setSidebarOpen(false);
                    }}
                    aria-pressed={label === entry.name}
                  >
                    {entry.name}
                  </button>
                ))
              )}
            </div>

            <form className="add-feed" onSubmit={submitLabel}>
              <label className="sr-only" htmlFor="label-name">
                New label
              </label>
              <input
                id="label-name"
                type="text"
                value={newLabel}
                onChange={(event) => setNewLabel(event.target.value)}
                placeholder="New label"
                maxLength={100}
                autoComplete="off"
              />
              <button
                type="submit"
                className="primary-button"
                disabled={addingLabel || !newLabel.trim()}
              >
                {addingLabel ? "Adding…" : "Add label"}
              </button>
            </form>
          </section>

          <div className="keys" aria-hidden="true">
            <span>
              <kbd>j</kbd>
              <kbd>k</kbd> move
            </span>
            <span>
              <kbd>s</kbd> star
            </span>
            <span>
              <kbd>m</kbd> read
            </span>
            <span>
              <kbd>r</kbd> refresh
            </span>
            <span>
              <kbd>/</kbd> search
            </span>
          </div>
        </aside>

        <section
          className="panel list-panel"
          aria-label="Story list"
          aria-busy={loading}
        >
          <div className="list-head">
            <div>
              <p className="eyebrow">{eyebrow}</p>
              <h1>{heading}</h1>
            </div>
            <span className="list-count">
              {loading ? "Loading…" : plural(total, "item")}
            </span>
          </div>

          {loading && items.length === 0 ? (
            <div className="item-list" aria-hidden="true">
              {[0, 1, 2, 3, 4].map((row) => (
                <div className="skeleton-row" key={row}>
                  <span />
                  <span />
                  <span />
                </div>
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="empty-list">
              <span className="empty-mark">
                <StreamIcon />
              </span>
              <h2>{emptyTitle}</h2>
              <p>{emptyBody}</p>
              {feeds.length === 0 && (
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => document.getElementById("feed-url")?.focus()}
                >
                  Add a feed
                </button>
              )}
            </div>
          ) : (
            <div className="item-list">
              {items.map((item, index) => {
                const preview = excerpt(item.content);
                return (
                  <button
                    key={item.id}
                    id={`item-${item.id}`}
                    type="button"
                    className={`item-row ${item.is_read ? "read" : "unread"} ${
                      selectedId === item.id ? "selected" : ""
                    }`}
                    style={
                      { "--row-index": Math.min(index, 12) } as CSSProperties
                    }
                    onClick={() => openItem(item)}
                    aria-current={selectedId === item.id ? "true" : undefined}
                  >
                    <span className="stream-dot" aria-hidden="true" />
                    <span className="item-row-body">
                      <span className="item-row-top">
                        <span className="item-feed">
                          {feedNames.get(item.feed_id) ?? "Unknown feed"}
                        </span>
                        <span className="item-date">
                          {formatRelative(item.published ?? item.fetched_at)}
                        </span>
                      </span>
                      <span className="item-title">
                        {item.title || "Untitled"}
                      </span>
                      {preview && (
                        <span className="item-excerpt">{preview}</span>
                      )}
                      {item.labels.length > 0 && (
                        <span className="item-labels">
                          {item.labels.map((entry) => (
                            <span className="item-label" key={entry.id}>
                              {entry.name}
                            </span>
                          ))}
                        </span>
                      )}
                    </span>
                    {item.starred && (
                      <StarIcon filled className="item-star" />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <article className="panel reading-pane" ref={readingRef}>
          {selected ? (
            <>
              <div className="reading-kicker">
                <span className="reading-source">
                  {feedNames.get(selected.feed_id) ?? "Unknown feed"}
                </span>
                <span>
                  {formatFullDate(selected.published ?? selected.fetched_at)}
                </span>
                {readingTime > 0 && <span>{readingTime} min read</span>}
                {selected.decision && (
                  <span>{selected.decision === "keep" ? "Kept" : "Dropped"}</span>
                )}
              </div>

              <h1>{selected.title || "Untitled"}</h1>

              <div className="reading-labels">
                <span className="eyebrow">Labels</span>
                <div className="label-cloud">
                  {labels.length === 0 ? (
                    <span className="muted small">
                      Create one in the sidebar to tag this item.
                    </span>
                  ) : (
                    labels.map((entry) => {
                      const attached = selected.labels.some(
                        (itemLabel) => itemLabel.id === entry.id,
                      );
                      return (
                        <button
                          key={entry.id}
                          type="button"
                          className={`label-chip ${attached ? "active" : ""}`}
                          onClick={() => void toggleLabel(selected, entry)}
                          aria-pressed={attached}
                        >
                          {entry.name}
                        </button>
                      );
                    })
                  )}
                </div>
              </div>

              <div className="reading-actions">
                <button
                  type="button"
                  className={`action-button ${selected.starred ? "active" : ""}`}
                  onClick={() => toggleStar(selected)}
                  aria-pressed={selected.starred}
                >
                  <StarIcon filled={selected.starred} />
                  {selected.starred ? "Starred" : "Star"}
                </button>

                <button
                  type="button"
                  className="action-button"
                  onClick={() => toggleRead(selected)}
                >
                  <CheckIcon />
                  {selected.is_read ? "Mark unread" : "Mark read"}
                </button>

                {selected.link && (
                  <a
                    className="action-button link-button"
                    href={selected.link}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalIcon />
                    Open original
                  </a>
                )}
              </div>

              <div className="reading-body">
                {readingBody || (
                  <span className="muted">
                    This feed only included a title. Open the original to read
                    the rest.
                  </span>
                )}
              </div>

              <div className="taste-row">
                <span className="eyebrow">Your taste</span>
                <div className="taste-buttons">
                  <button
                    type="button"
                    className={`taste-button ${
                      selected.decision === "keep" ? "keep" : ""
                    }`}
                    onClick={() => toggleDecision(selected, "keep")}
                    aria-pressed={selected.decision === "keep"}
                  >
                    Keep
                  </button>
                  <button
                    type="button"
                    className={`taste-button ${
                      selected.decision === "drop" ? "drop" : ""
                    }`}
                    onClick={() => toggleDecision(selected, "drop")}
                    aria-pressed={selected.decision === "drop"}
                  >
                    Drop
                  </button>
                </div>
                <span className="taste-hint">
                  <SparkIcon /> A local training signal. Nothing leaves this
                  machine.
                </span>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <span className="empty-mark">
                <StreamIcon />
              </span>
              <h2>{loading ? "Opening the stream" : "Choose an item"}</h2>
              <p>
                {loading
                  ? "Reading the local database."
                  : "Pick a story from the list. The full text stays in your own database."}
              </p>
            </div>
          )}
        </article>
      </main>

      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          <span>{toast.message}</span>
          <button
            type="button"
            onClick={() => setToast(null)}
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
