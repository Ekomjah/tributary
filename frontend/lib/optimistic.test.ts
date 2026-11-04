import { afterEach, describe, expect, it } from "vitest";
import { QueryClient, type InfiniteData } from "@tanstack/react-query";

import {
  applyIntent,
  clearItemOverlay,
  countDelta,
  itemMatchesScope,
  mergeIntents,
  optimisticItem,
  optimisticPage,
  resetItemOverlays,
  scopeMembershipDelta,
  setItemOverlay,
  writeItemToCaches,
} from "./optimistic";
import type { Counts, Item, ItemPage } from "./types";

function makeItem(id: number, overrides: Partial<Item> = {}): Item {
  return {
    id,
    feed_id: 7,
    guid: `guid-${id}`,
    title: `Item ${id}`,
    link: null,
    published: null,
    content: "",
    content_html: null,
    author: null,
    cover_image: null,
    cover_image_alt: null,
    cover_caption: null,
    content_full: null,
    content_fetched_at: null,
    fetch_status: null,
    discussion_url: null,
    points: null,
    comment_count: null,
    shared_by: null,
    shared_at: null,
    origin_feed_title: null,
    source: null,
    is_read: false,
    starred: false,
    decision: null,
    fetched_at: "2026-01-01T00:00:00Z",
    labels: [],
    summary: null,
    why_care: null,
    ...overrides,
  };
}

function makePage(items: Item[], total = items.length): ItemPage {
  return { items, total, limit: 20, offset: 0 };
}

afterEach(() => {
  resetItemOverlays();
});

describe("applyIntent", () => {
  it("sets absolute flags and labels", () => {
    const item = makeItem(1);
    const next = applyIntent(item, {
      patch: { is_read: true, starred: true, decision: "keep" },
      labels: [{ id: 4, name: "Later" }],
    });

    expect(next).toMatchObject({
      is_read: true,
      starred: true,
      decision: "keep",
      labels: [{ id: 4, name: "Later" }],
    });
    expect(item.is_read).toBe(false);
  });

  it("keeps fields the intent does not mention", () => {
    const item = makeItem(1, { is_read: true, starred: true });
    expect(applyIntent(item, { patch: { decision: null } })).toMatchObject({
      is_read: true,
      starred: true,
      decision: null,
    });
  });
});

describe("mergeIntents", () => {
  it("lets the newer intent win per field", () => {
    const merged = mergeIntents(
      { patch: { starred: true, is_read: true } },
      { patch: { starred: false } },
    );

    expect(merged?.patch).toEqual({ starred: false, is_read: true });
  });

  it("keeps labels paired with the newest label_ids", () => {
    const older = [{ id: 1, name: "One" }];
    const newer = [{ id: 1, name: "One" }, { id: 2, name: "Two" }];
    const merged = mergeIntents(
      { patch: { label_ids: [1], starred: true }, labels: older },
      { patch: { label_ids: [1, 2], is_read: true }, labels: newer },
    );

    expect(merged?.patch).toEqual({
      label_ids: [1, 2],
      starred: true,
      is_read: true,
    });
    expect(merged?.labels).toEqual(newer);
  });

  it("carries labels forward when only other fields change", () => {
    const labels = [{ id: 2, name: "Two" }];
    const merged = mergeIntents(
      { patch: { label_ids: [2] }, labels },
      { patch: { starred: true } },
    );

    expect(merged?.patch).toEqual({ label_ids: [2], starred: true });
    expect(merged?.labels).toEqual(labels);
  });
});

describe("countDelta", () => {
  it("counts a star", () => {
    expect(countDelta(makeItem(1), makeItem(1, { starred: true }))).toEqual({
      starred: 1,
      unread: 0,
      feedId: 7,
      feedUnread: 0,
    });
  });

  it("counts a read toggle in both the view and the feed", () => {
    expect(countDelta(makeItem(1), makeItem(1, { is_read: true }))).toEqual({
      starred: 0,
      unread: -1,
      feedId: 7,
      feedUnread: -1,
    });
    expect(
      countDelta(makeItem(1, { is_read: true }), makeItem(1, { is_read: false })),
    ).toMatchObject({ unread: 1, feedUnread: 1 });
  });
});

describe("scope membership", () => {
  const scope = {
    view: "unread" as const,
    feedId: null,
    label: null,
    query: "",
  };

  it("knows the filtered views", () => {
    expect(itemMatchesScope(makeItem(1), scope)).toBe(true);
    expect(itemMatchesScope(makeItem(1, { is_read: true }), scope)).toBe(false);
    expect(
      itemMatchesScope(makeItem(1, { starred: false }), {
        ...scope,
        view: "starred",
      }),
    ).toBe(false);
  });

  it("matches labels case-insensitively and skips searches", () => {
    const item = makeItem(1, { labels: [{ id: 1, name: "Long Reads" }] });
    expect(itemMatchesScope(item, { ...scope, label: "long reads" })).toBe(
      true,
    );
    expect(itemMatchesScope(item, { ...scope, label: "news" })).toBe(false);
    expect(itemMatchesScope(item, { ...scope, query: "rust" })).toBeNull();
  });

  it("returns the total change for a scope", () => {
    const item = makeItem(1);
    const base = { ...scope, view: "starred" as const };
    expect(scopeMembershipDelta(item, { ...item, starred: true }, base)).toBe(
      1,
    );
    expect(
      scopeMembershipDelta({ ...item, starred: true }, item, base),
    ).toBe(-1);
    expect(scopeMembershipDelta(item, item, base)).toBe(0);
    expect(
      scopeMembershipDelta(item, { ...item, starred: true }, {
        ...base,
        query: "rust",
      }),
    ).toBeNull();
  });
});

describe("overlay registry", () => {
  it("layers an intent over a fetched item and clears it", () => {
    const item = makeItem(1, { starred: false });
    setItemOverlay(1, { patch: { starred: true } });

    expect(optimisticItem(item).starred).toBe(true);
    expect(item.starred).toBe(false);

    clearItemOverlay(1);
    expect(optimisticItem(item)).toBe(item);
  });

  it("repairs a page and its total when a fetch races a toggle", () => {
    setItemOverlay(1, { patch: { starred: false } });
    const fetched = makePage([makeItem(1, { starred: true })], 3);

    const page = optimisticPage(fetched, {
      view: "starred",
      feedId: null,
      label: null,
      query: "",
    });

    expect(page.items[0]?.starred).toBe(false);
    expect(page.total).toBe(2);
  });

  it("leaves pages alone when there is no pending intent", () => {
    const fetched = makePage([makeItem(1)], 1);
    expect(optimisticPage(fetched)).toBe(fetched);
  });
});

describe("writeItemToCaches", () => {
  it("updates rows, totals, counters, and reverses cleanly", () => {
    const client = new QueryClient();
    const base = makeItem(1, { starred: true });
    const key = ["items", "starred", null, null, ""] as const;

    client.setQueryData<InfiniteData<ItemPage>>(key, {
      pages: [makePage([base], 1)],
      pageParams: [0],
    });
    client.setQueryData<Item>(["item", 1], base);
    client.setQueryData<Counts>(["counts", "7"], {
      views: { all: 4, unread: 2, starred: 1 },
      feeds: { 7: 2 },
    });

    const optimistic = applyIntent(base, {
      patch: { starred: false, is_read: true },
    });
    writeItemToCaches(client, 1, optimistic);

    expect(
      client.getQueryData<InfiniteData<ItemPage>>(key)?.pages[0]?.items[0]
        ?.starred,
    ).toBe(false);
    expect(
      client.getQueryData<InfiniteData<ItemPage>>(key)?.pages[0]?.total,
    ).toBe(0);
    expect(client.getQueryData<Item>(["item", 1])?.is_read).toBe(true);
    expect(client.getQueryData<Counts>(["counts", "7"])).toEqual({
      views: { all: 4, unread: 1, starred: 0 },
      feeds: { 7: 1 },
    });

    writeItemToCaches(client, 1, base);

    expect(
      client.getQueryData<InfiniteData<ItemPage>>(key)?.pages[0]?.items[0]
        ?.starred,
    ).toBe(true);
    expect(
      client.getQueryData<InfiniteData<ItemPage>>(key)?.pages[0]?.total,
    ).toBe(1);
    expect(client.getQueryData<Counts>(["counts", "7"])).toEqual({
      views: { all: 4, unread: 2, starred: 1 },
      feeds: { 7: 2 },
    });
  });

  it("does not touch totals for search scopes", () => {
    const client = new QueryClient();
    const base = makeItem(1);
    const key = ["items", "starred", null, null, "rust"] as const;
    client.setQueryData<InfiniteData<ItemPage>>(key, {
      pages: [makePage([base], 5)],
      pageParams: [0],
    });

    writeItemToCaches(client, 1, applyIntent(base, { patch: { starred: true } }));

    expect(
      client.getQueryData<InfiniteData<ItemPage>>(key)?.pages[0]?.total,
    ).toBe(5);
  });
});
