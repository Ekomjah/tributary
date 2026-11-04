import { describe, expect, it } from "vitest";
import type { InfiniteData } from "@tanstack/react-query";

import {
  articleHref,
  articleSlug,
  feedsHref,
  flattenItemPages,
  itemIdFromHash,
  itemIdFromSlug,
  itemsQueryOptions,
  mapItemPages,
  PAGE_SIZE,
  readScope,
  sameScope,
  sameScopeLocation,
  scopeAfterFeedDelete,
  scopeDescription,
  scopeKey,
  scopeLabel,
} from "./feeds";
import type { Feed, Item, ItemPage } from "./types";

const FEEDS: Feed[] = [
  {
    id: 3,
    url: "https://example.com/feed",
    title: "Example",
    kind: "feed",
    pipe_id: null,
    last_fetched: null,
    last_error: null,
    ingest_state: "ready",
    ingest_total: 0,
    ingest_processed: 0,
    ingest_error: null,
    created_at: "2026-10-28T10:00:00Z",
  },
];

function item(id: number): Item {
  return {
    id,
    feed_id: 3,
    guid: `guid-${id}`,
    title: `Item ${id}`,
    link: `https://example.com/${id}`,
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
    fetched_at: "2026-10-28T10:00:00Z",
    labels: [],
    summary: null,
    why_care: null,
  };
}

function page(offset: number, ids: number[], total: number): ItemPage {
  return { items: ids.map(item), total, limit: PAGE_SIZE, offset };
}

describe("readScope", () => {
  it("reads a full scope from the query string", () => {
    const scope = readScope(
      new URLSearchParams("view=unread&feed=3&q=sqlite"),
    );

    expect(scope).toEqual({
      view: "unread",
      feedId: 3,
      label: null,
      query: "sqlite",
    });
  });

  it("falls back to All items for an unknown view", () => {
    expect(readScope(new URLSearchParams("view=everything")).view).toBe("all");
  });

  it("drops a label when a feed is also present", () => {
    expect(readScope(new URLSearchParams("feed=3&label=Databases"))).toEqual({
      view: "all",
      feedId: 3,
      label: null,
      query: "",
    });
  });

  it("ignores a malformed feed id", () => {
    expect(readScope(new URLSearchParams("feed=abc")).feedId).toBeNull();
    expect(readScope(new URLSearchParams("feed=0")).feedId).toBeNull();
  });
});

describe("feedsHref", () => {
  it("keeps the default scope clean", () => {
    expect(
      feedsHref({ view: "all", feedId: null, label: null, query: "" }),
    ).toBe("/feeds");
  });

  it("encodes the active scope", () => {
    expect(
      feedsHref({
        view: "unread",
        feedId: null,
        label: "AI & ML",
        query: "local model",
      }),
    ).toBe("/feeds?view=unread&label=AI+%26+ML&q=local+model");
  });
});

describe("article slugs", () => {
  it("appends the item id to a readable title", () => {
    expect(articleSlug({ id: 42, title: "A Quiet Inbox" })).toBe(
      "a-quiet-inbox-42",
    );
  });

  it("uses the id alone when the title has no latin characters", () => {
    expect(articleSlug({ id: 42, title: "静かな受信箱" })).toBe("42");
  });

  it("parses the id from a title slug", () => {
    expect(itemIdFromSlug("a-quiet-inbox-42")).toBe(42);
    expect(itemIdFromSlug("top-10-databases-42")).toBe(42);
    expect(itemIdFromSlug("42")).toBe(42);
  });

  it("rejects slugs without a positive id", () => {
    expect(itemIdFromSlug("a-quiet-inbox")).toBeNull();
    expect(itemIdFromSlug("a-quiet-inbox-0")).toBeNull();
    expect(itemIdFromSlug("a-quiet-inbox-12x")).toBeNull();
  });

  it("carries the list scope into the article URL", () => {
    expect(
      articleHref(
        { id: 42, title: "A Quiet Inbox" },
        { view: "unread", feedId: 3, label: null, query: "" },
      ),
    ).toBe("/feeds/a-quiet-inbox-42?view=unread&feed=3");
  });
});

describe("scopeLabel", () => {
  it("names the current feed", () => {
    expect(
      scopeLabel(
        { view: "all", feedId: 3, label: null, query: "" },
        FEEDS,
      ),
    ).toBe("Example");
  });

  it("names search results first", () => {
    expect(
      scopeLabel(
        { view: "all", feedId: 3, label: null, query: "sqlite" },
        FEEDS,
      ),
    ).toBe("Search results");
  });
});

describe("scopeAfterFeedDelete", () => {
  it("returns to All items when the selected feed is deleted", () => {
    expect(
      scopeAfterFeedDelete(
        { view: "unread", feedId: 3, label: null, query: "sqlite" },
        3,
      ),
    ).toEqual({ view: "all", feedId: null, label: null, query: "" });
  });

  it("leaves the scope alone when another feed is deleted", () => {
    expect(
      scopeAfterFeedDelete(
        { view: "all", feedId: 3, label: null, query: "" },
        4,
      ),
    ).toBeNull();
  });
});

describe("item hashes", () => {
  it("round-trips an item id", () => {
    expect(itemIdFromHash("#item-42")).toBe(42);
    expect(itemIdFromHash("#inbox")).toBeNull();
  });
});

describe("scope comparison", () => {
  it("treats every part of the scope as significant", () => {
    const base = { view: "all", feedId: 3, label: null, query: "" } as const;
    expect(sameScope(base, { ...base })).toBe(true);
    expect(sameScope(base, { ...base, query: "sqlite" })).toBe(false);
    expect(sameScope(base, { ...base, feedId: null })).toBe(false);
  });

  it("ignores search when comparing what a sidebar row points at", () => {
    expect(
      sameScopeLocation(
        { view: "all", feedId: null, label: null, query: "sqlite" },
        { view: "all", feedId: null, label: null, query: "" },
      ),
    ).toBe(true);
  });

  it("builds a stable key for the whole scope", () => {
    expect(
      scopeKey({ view: "unread", feedId: 3, label: null, query: "sqlite" }),
    ).toBe("unread|3||sqlite");
  });

  it("shares the query key between the list and prefetching", () => {
    expect(
      itemsQueryOptions({
        view: "unread",
        feedId: 3,
        label: null,
        query: "sqlite",
      }).queryKey,
    ).toEqual(["items", "unread", 3, null, "sqlite"]);
  });
});

describe("item pages", () => {
  const scope = {
    view: "all",
    feedId: null,
    label: null,
    query: "",
  } as const;

  it("uses the feed batch size for the first page", () => {
    expect(PAGE_SIZE).toBe(20);
    expect(itemsQueryOptions(scope).initialPageParam).toBe(0);
  });

  it("computes the next offset from the rows that came back", () => {
    const options = itemsQueryOptions(scope);

    expect(options.getNextPageParam(page(0, [1, 2], 4))).toBe(2);
    expect(options.getNextPageParam(page(2, [3, 4], 4))).toBeUndefined();
    expect(options.getNextPageParam(page(0, [], 0))).toBeUndefined();
  });

  it("flattens pages and drops rows repeated by offset drift", () => {
    const data: InfiniteData<ItemPage> = {
      pages: [page(0, [1, 2], 4), page(2, [2, 3], 4)],
      pageParams: [0, 2],
    };

    expect(flattenItemPages(data).map((entry) => entry.id)).toEqual([1, 2, 3]);
    expect(flattenItemPages(undefined)).toEqual([]);
  });

  it("applies an item mutation to every cached page", () => {
    const data: InfiniteData<ItemPage> = {
      pages: [page(0, [1, 2], 4), page(2, [3, 4], 4)],
      pageParams: [0, 2],
    };

    const mapped = mapItemPages(data, (entry) => ({
      ...entry,
      starred: true,
    }));

    expect(mapped?.pages.map((entry) => entry.total)).toEqual([4, 4]);
    expect(
      mapped?.pages.flatMap((entry) =>
        entry.items.map((row) => [row.id, row.starred]),
      ),
    ).toEqual([
      [1, true],
      [2, true],
      [3, true],
      [4, true],
    ]);
    expect(mapItemPages(undefined, (entry) => entry)).toBeUndefined();
  });
});

describe("scopeDescription", () => {
  it("names a view", () => {
    expect(
      scopeDescription(
        { view: "unread", feedId: null, label: null, query: "" },
        FEEDS,
      ),
    ).toBe("Unread");
  });

  it("names a feed", () => {
    expect(
      scopeDescription(
        { view: "all", feedId: 3, label: null, query: "" },
        FEEDS,
      ),
    ).toBe("“Example”");
  });

  it("names a search first", () => {
    expect(
      scopeDescription(
        { view: "all", feedId: null, label: null, query: "sqlite" },
        FEEDS,
      ),
    ).toBe("results for “sqlite”");
  });

  it("names a label", () => {
    expect(
      scopeDescription(
        { view: "all", feedId: null, label: "AI", query: "" },
        FEEDS,
      ),
    ).toBe("label “AI”");
  });
});
