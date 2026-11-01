import { api } from "./api";
import { hostOf, slugify } from "./text";
import type { Feed, Item, ItemView } from "./types";

export const VIEWS: ItemView[] = ["all", "unread", "starred"];
export const VIEW_NAMES: Record<ItemView, string> = {
  all: "All items",
  unread: "Unread",
  starred: "Starred items",
};
export const PAGE_SIZE = 100;

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
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      api.listItems({
        unread: scope.view === "unread" ? true : undefined,
        starred: scope.view === "starred" ? true : undefined,
        feedId: scope.feedId,
        label: scope.label,
        q: scope.query || undefined,
        limit: PAGE_SIZE,
        signal,
      }),
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
