import type { InfiniteData, QueryClient } from "@tanstack/react-query";

import type {
  Counts,
  Item,
  ItemPage,
  ItemUpdate,
  ItemView,
  Label,
} from "./types";

/**
 * The desired end state of one item. Every field is absolute rather than a
 * delta, so applying it twice is harmless and a retry can never drift.
 */
export interface ItemIntent {
  patch: ItemUpdate;
  /** Carried alongside `label_ids` so the UI has label objects immediately. */
  labels?: Label[];
}

/** The subset of a feed scope that we can evaluate on the client. */
export interface ItemScope {
  view: ItemView;
  feedId: number | null;
  label: string | null;
  query: string;
}

export interface CountDelta {
  starred: number;
  unread: number;
  feedId: number;
  feedUnread: number;
}

/**
 * Pending intents keyed by item, layered over any item that arrives from the
 * server. Without this, a GET issued at the same moment as a PATCH can land
 * afterwards and silently undo the optimistic value.
 */
const overlays = new Map<number, ItemIntent>();

export function setItemOverlay(itemId: number, intent: ItemIntent): void {
  overlays.set(itemId, intent);
}

export function clearItemOverlay(itemId: number): void {
  overlays.delete(itemId);
}

export function resetItemOverlays(): void {
  overlays.clear();
}

export function hasItemOverlay(itemId: number): boolean {
  return overlays.has(itemId);
}

export function applyIntent(item: Item, intent: ItemIntent): Item {
  const { patch } = intent;
  return {
    ...item,
    is_read: patch.is_read ?? item.is_read,
    starred: patch.starred ?? item.starred,
    decision: "decision" in patch ? (patch.decision ?? null) : item.decision,
    labels: intent.labels ?? item.labels,
  };
}

export function optimisticItem(item: Item): Item {
  const intent = overlays.get(item.id);
  return intent ? applyIntent(item, intent) : item;
}

/** Merge a newer intent on top of an older one; later fields win. */
export function mergeIntents(
  previous: ItemIntent | undefined,
  next: ItemIntent | undefined,
): ItemIntent | undefined {
  if (!previous) {
    return next;
  }
  if (!next) {
    return previous;
  }

  const patch: ItemUpdate = { ...previous.patch, ...next.patch };
  let labels: Label[] | undefined;
  if ("label_ids" in next.patch) {
    labels = next.labels;
  } else if ("label_ids" in previous.patch) {
    labels = previous.labels;
  }

  return labels === undefined ? { patch } : { patch, labels };
}

export function countDelta(previous: Item, next: Item): CountDelta {
  const readDelta = Number(!next.is_read) - Number(!previous.is_read);
  return {
    starred: Number(next.starred) - Number(previous.starred),
    unread: readDelta,
    feedId: previous.feed_id,
    feedUnread:
      previous.feed_id === next.feed_id &&
      previous.is_read !== next.is_read
        ? readDelta
        : 0,
  };
}

function normalizeLabelName(name: string): string {
  return name.trim().toLowerCase();
}

/**
 * Whether an item belongs in a scope. `null` means the client cannot know
 * (a full-text search), so callers must leave totals alone.
 */
export function itemMatchesScope(
  item: Item,
  scope: ItemScope,
): boolean | null {
  if (scope.query) {
    return null;
  }
  if (scope.feedId !== null && item.feed_id !== scope.feedId) {
    return false;
  }
  if (scope.label !== null) {
    const key = normalizeLabelName(scope.label);
    if (!item.labels.some((label) => normalizeLabelName(label.name) === key)) {
      return false;
    }
  }
  if (scope.view === "unread" && item.is_read) {
    return false;
  }
  if (scope.view === "starred" && !item.starred) {
    return false;
  }
  return true;
}

export function scopeMembershipDelta(
  previous: Item,
  next: Item,
  scope: ItemScope,
): number | null {
  const before = itemMatchesScope(previous, scope);
  const after = itemMatchesScope(next, scope);
  if (before === null || after === null) {
    return null;
  }
  return Number(after) - Number(before);
}

export function readCachedItem(
  queryClient: QueryClient,
  itemId: number,
): Item | null {
  const direct = queryClient.getQueryData<Item>(["item", itemId]);
  if (direct) {
    return direct;
  }

  for (const [, data] of queryClient.getQueriesData<
    InfiniteData<ItemPage>
  >({ queryKey: ["items"] })) {
    if (!data) {
      continue;
    }
    for (const page of data.pages) {
      const row = page.items.find((entry) => entry.id === itemId);
      if (row) {
        return row;
      }
    }
  }
  return null;
}

function scopeFromItemsKey(key: readonly unknown[]): ItemScope | null {
  if (key[0] !== "items" || key.length < 5) {
    return null;
  }
  const [, view, feedId, label, query] = key;
  if (view !== "all" && view !== "unread" && view !== "starred") {
    return null;
  }
  if (feedId !== null && typeof feedId !== "number") {
    return null;
  }
  if (label !== null && typeof label !== "string") {
    return null;
  }
  if (typeof query !== "string") {
    return null;
  }
  return { view, feedId, label, query };
}

/**
 * Overlay pending intents on a page fetched from the server, correcting the
 * scope total when the overlay moves an item out of the filter.
 */
export function optimisticPage(page: ItemPage, scope?: ItemScope): ItemPage {
  let total = page.total;
  let changed = false;
  const items = page.items.map((item) => {
    const next = optimisticItem(item);
    if (next === item) {
      return item;
    }
    changed = true;
    if (scope) {
      const delta = scopeMembershipDelta(item, next, scope);
      if (delta !== null) {
        total += delta;
      }
    }
    return next;
  });

  if (!changed) {
    return page;
  }
  return { ...page, items, total: Math.max(0, total) };
}

/**
 * Write an item into every cached list, the detail cache, and the counters.
 * Works in both directions: pass the optimistic value to apply a change, or
 * the confirmed base to roll one back.
 */
export function writeItemToCaches(
  queryClient: QueryClient,
  itemId: number,
  next: Item,
): void {
  const previous = readCachedItem(queryClient, itemId);
  const delta = previous ? countDelta(previous, next) : null;

  for (const [key, data] of queryClient.getQueriesData<
    InfiniteData<ItemPage>
  >({ queryKey: ["items"] })) {
    if (!data) {
      continue;
    }
    const scope = scopeFromItemsKey(key);
    const membership =
      previous && scope ? scopeMembershipDelta(previous, next, scope) : null;

    queryClient.setQueryData<InfiniteData<ItemPage>>(key, {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((row) => (row.id === itemId ? next : row)),
        total:
          membership === null
            ? page.total
            : Math.max(0, page.total + membership),
      })),
    });
  }

  queryClient.setQueryData<Item>(["item", itemId], next);

  if (!delta || (delta.starred === 0 && delta.unread === 0)) {
    return;
  }

  for (const [key, counts] of queryClient.getQueriesData<Counts>({
    queryKey: ["counts"],
  })) {
    if (!counts) {
      continue;
    }
    queryClient.setQueryData<Counts>(key, {
      views: {
        ...counts.views,
        unread: Math.max(0, counts.views.unread + delta.unread),
        starred: Math.max(0, counts.views.starred + delta.starred),
      },
      feeds:
        delta.feedUnread === 0
          ? counts.feeds
          : {
              ...counts.feeds,
              [delta.feedId]: Math.max(
                0,
                (counts.feeds[delta.feedId] ?? 0) + delta.feedUnread,
              ),
            },
    });
  }
}
