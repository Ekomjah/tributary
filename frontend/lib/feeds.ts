import type { InfiniteData } from "@tanstack/react-query";

import { api } from "./api";
import { optimisticPage } from "./optimistic";
import { hostOf, slugify } from "./text";
import type { Feed, Item, ItemPage, ItemView } from "./types";

export const VIEWS: ItemView[] = ["all", "unread", "starred"];
export const VIEW_NAMES: Record<ItemView, string> = {
  all: "All items",
  unread: "Unread",
  starred: "Starred items",
};
export const PAGE_SIZE = 20;

export interface FeedsScope {
  view: ItemView;
  feedId: number | null;
  label: string | null;
  query: string;
}

interface ScopeReader {
  get(key: string): string | null;
}

export function readScope(params: ScopeReader): FeedsScope {
  const rawView = params.get("view");
  const view = VIEWS.includes(rawView as ItemView)
    ? (rawView as ItemView)
    : "all";

  const rawFeed = params.get("feed");
  const feedId =
    rawFeed && /^\d+$/.test(rawFeed) && Number(rawFeed) > 0
      ? Number(rawFeed)
      : null;

  return {
    view,
    feedId,
    label: feedId === null ? params.get("label") : null,
    query: params.get("q")?.trim() ?? "",
  };
}

export function feedsHref(scope: FeedsScope): string {
  const params = new URLSearchParams();
  if (scope.view !== "all") {
    params.set("view", scope.view);
  }
  if (scope.feedId !== null) {
    params.set("feed", String(scope.feedId));
  }
  if (scope.label) {
    params.set("label", scope.label);
  }
  if (scope.query) {
    params.set("q", scope.query);
  }

  const query = params.toString();
  return query ? `/feeds?${query}` : "/feeds";
}

export function scopeLabel(scope: FeedsScope, feeds: Feed[]): string {
  if (scope.query) {
    return "Search results";
  }
  if (scope.label) {
    return scope.label;
  }
  if (scope.feedId !== null) {
    const feed = feeds.find((entry) => entry.id === scope.feedId);
    return feed ? feed.title || hostOf(feed.url) : "All items";
  }
  return VIEW_NAMES[scope.view];
}

export function itemsQueryKey(scope: FeedsScope) {
  return ["items", scope.view, scope.feedId, scope.label, scope.query] as const;
}

export function itemsQueryOptions(scope: FeedsScope) {
  return {
    queryKey: itemsQueryKey(scope),
    initialPageParam: 0,
    queryFn: async ({
      pageParam,
      signal,
    }: {
      pageParam: number;
      signal: AbortSignal;
    }) => {
      const page = await api.listItems({
        unread: scope.view === "unread" ? true : undefined,
        starred: scope.view === "starred" ? true : undefined,
        feedId: scope.feedId,
        label: scope.label,
        q: scope.query || undefined,
        limit: PAGE_SIZE,
        offset: pageParam,
        signal,
      });
      // A fetch that was in flight when a toggle happened must not undo the
      // optimistic value it raced with.
      return optimisticPage(page, scope);
    },
    getNextPageParam: (lastPage: ItemPage) => {
      const next = lastPage.offset + lastPage.items.length;
      return lastPage.items.length > 0 && next < lastPage.total
        ? next
        : undefined;
    },
  };
}

/** Flatten the loaded pages and drop rows duplicated by offset drift. */
export function flattenItemPages(
  data: InfiniteData<ItemPage> | undefined,
): Item[] {
  if (!data) {
    return [];
  }

  const seen = new Set<number>();
  const items: Item[] = [];
  for (const page of data.pages) {
    for (const item of page.items) {
      if (seen.has(item.id)) {
        continue;
      }
      seen.add(item.id);
      items.push(item);
    }
  }
  return items;
}

/** Apply a mutation result to every cached page of an infinite item list. */
export function mapItemPages(
  data: InfiniteData<ItemPage> | undefined,
  update: (item: Item) => Item,
): InfiniteData<ItemPage> | undefined {
  if (!data) {
    return data;
  }
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.map(update),
    })),
  };
}

export function sameScope(left: FeedsScope, right: FeedsScope): boolean {
  return (
    left.view === right.view &&
    left.feedId === right.feedId &&
    left.label === right.label &&
    left.query === right.query
  );
}

/** Compare only what the sidebar and view tabs point at, ignoring search. */
export function sameScopeLocation(
  left: FeedsScope,
  right: FeedsScope,
): boolean {
  return (
    left.view === right.view &&
    left.feedId === right.feedId &&
    left.label === right.label
  );
}

export function scopeKey(scope: FeedsScope): string {
  return `${scope.view}|${scope.feedId ?? ""}|${scope.label ?? ""}|${scope.query}`;
}

export function scopeDescription(scope: FeedsScope, feeds: Feed[]): string {
  if (scope.query) {
    return `results for “${scope.query}”`;
  }
  if (scope.label) {
    return `label “${scope.label}”`;
  }
  if (scope.feedId !== null) {
    const feed = feeds.find((entry) => entry.id === scope.feedId);
    return feed ? `“${feed.title || hostOf(feed.url)}”` : "the feed";
  }
  return VIEW_NAMES[scope.view];
}

export function scopeAfterFeedDelete(
  scope: FeedsScope,
  feedId: number,
): FeedsScope | null {
  if (scope.feedId !== feedId) {
    return null;
  }
  return { view: "all", feedId: null, label: null, query: "" };
}

export function articleSlug(item: Pick<Item, "id" | "title">): string {
  const slug = slugify(item.title).slice(0, 60).replace(/-+$/, "");
  return slug ? `${slug}-${item.id}` : String(item.id);
}

export function itemIdFromSlug(slug: string): number | null {
  const match = /(?:^|-)(\d+)$/.exec(slug);
  if (!match) {
    return null;
  }

  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function articleHref(
  item: Pick<Item, "id" | "title">,
  scope: FeedsScope,
): string {
  return `/feeds/${articleSlug(item)}${feedsHref(scope).slice("/feeds".length)}`;
}

export function itemHash(itemId: number): string {
  return `#item-${itemId}`;
}

export function itemIdFromHash(hash: string): number | null {
  const match = /^#item-(\d+)$/.exec(hash);
  if (!match) {
    return null;
  }

  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
