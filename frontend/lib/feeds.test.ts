import { describe, expect, it } from "vitest";

import {
  articleHref,
  articleSlug,
  feedsHref,
  itemIdFromHash,
  itemIdFromSlug,
  readScope,
  scopeAfterFeedDelete,
  scopeLabel,
} from "./feeds";
import type { Feed } from "./types";

const FEEDS: Feed[] = [
  {
    id: 3,
    url: "https://example.com/feed",
    title: "Example",
    kind: "feed",
    pipe_id: null,
    last_fetched: null,
    last_error: null,
    created_at: "2026-10-28T10:00:00Z",
  },
];

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
