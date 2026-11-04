import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, type InfiniteData } from "@tanstack/react-query";

import { api, ApiError } from "./api";
import {
  enqueueItemMutation,
  resetItemMutations,
  type ItemMutationContext,
  type ItemMutationFailure,
} from "./item-mutations";
import { applyIntent } from "./optimistic";
import type { Counts, Item, ItemPage } from "./types";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    api: { ...actual.api, updateItem: vi.fn() },
  };
});

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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

let client: QueryClient;
let failures: ItemMutationFailure[];

function seed(item: Item) {
  client.setQueryData<Item>(["item", item.id], item);
  client.setQueryData<InfiniteData<ItemPage>>(
    ["items", "all", null, null, ""],
    {
      pages: [{ items: [item], total: 1, limit: 20, offset: 0 }],
      pageParams: [0],
    },
  );
}

function cachedItem(id = 1): Item | undefined {
  return client.getQueryData<Item>(["item", id]);
}

function readCounts(): Counts | undefined {
  return client.getQueryData<Counts>(["counts", "7"]);
}

function context(): ItemMutationContext {
  return {
    queryClient: client,
    onFailure: (failure) => failures.push(failure),
  };
}

beforeEach(() => {
  client = new QueryClient();
  failures = [];
});

afterEach(() => {
  resetItemMutations();
  vi.mocked(api.updateItem).mockReset();
  client.clear();
});

describe("enqueueItemMutation", () => {
  it("applies the change before the request resolves", async () => {
    const item = makeItem(1);
    seed(item);
    const request = deferred<Item>();
    vi.mocked(api.updateItem).mockReturnValueOnce(request.promise);

    const done = enqueueItemMutation(
      item,
      { patch: { starred: true } },
      context(),
    );

    expect(cachedItem()?.starred).toBe(true);
    expect(api.updateItem).toHaveBeenCalledWith(1, { starred: true });

    request.resolve({ ...item, starred: true });
    await done;
    expect(cachedItem()?.starred).toBe(true);
  });

  it("merges rapid clicks into one follow-up request", async () => {
    const item = makeItem(1);
    seed(item);
    const first = deferred<Item>();
    const second = deferred<Item>();
    vi.mocked(api.updateItem)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const done = enqueueItemMutation(
      item,
      { patch: { starred: true } },
      context(),
    );
    const alsoDone = enqueueItemMutation(
      item,
      { patch: { is_read: true } },
      context(),
    );

    expect(cachedItem()?.starred).toBe(true);
    expect(cachedItem()?.is_read).toBe(true);

    first.resolve({ ...item, starred: true });
    await vi.waitFor(() =>
      expect(api.updateItem).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.updateItem).mock.calls[1]).toEqual([
      1,
      { is_read: true },
    ]);

    second.resolve({ ...item, starred: true, is_read: true });
    await Promise.all([done, alsoDone]);

    expect(cachedItem()).toMatchObject({ starred: true, is_read: true });
  });

  it("rolls back to the last confirmed state and offers a retry", async () => {
    const item = makeItem(1);
    seed(item);
    vi.mocked(api.updateItem).mockRejectedValueOnce(
      new ApiError("The API refused that change.", 422),
    );

    await enqueueItemMutation(
      item,
      { patch: { starred: true } },
      context(),
    );

    expect(cachedItem()?.starred).toBe(false);
    expect(failures).toHaveLength(1);
    expect(failures[0]?.itemId).toBe(1);

    vi.mocked(api.updateItem).mockResolvedValueOnce({
      ...item,
      starred: true,
    });
    failures[0]?.retry();

    await vi.waitFor(() => expect(cachedItem()?.starred).toBe(true));
  });

  it("retries the latest state when a click queued behind a failure", async () => {
    const item = makeItem(1);
    seed(item);
    const first = deferred<Item>();
    vi.mocked(api.updateItem).mockReturnValueOnce(first.promise);

    const done = enqueueItemMutation(
      item,
      { patch: { starred: true } },
      context(),
    );
    const alsoDone = enqueueItemMutation(
      item,
      { patch: { is_read: true } },
      context(),
    );

    first.reject(new ApiError("The API refused that change.", 422));
    await Promise.all([done, alsoDone]);

    expect(cachedItem()).toMatchObject({ starred: false, is_read: false });
    expect(failures).toHaveLength(1);

    const updated = { ...item, starred: true, is_read: true };
    vi.mocked(api.updateItem).mockResolvedValueOnce(updated);
    failures[0]?.retry();

    await vi.waitFor(() => expect(cachedItem()).toEqual(updated));
    expect(vi.mocked(api.updateItem).mock.calls[1]).toEqual([
      1,
      { is_read: true, starred: true },
    ]);
  });

  it("rolls back quietly for auto mark-as-read", async () => {
    const item = makeItem(1);
    seed(item);
    vi.mocked(api.updateItem).mockRejectedValueOnce(
      new ApiError("The API refused that change.", 422),
    );

    await enqueueItemMutation(
      item,
      { patch: { is_read: true } },
      { ...context(), silent: true },
    );

    expect(cachedItem()?.is_read).toBe(false);
    expect(failures).toHaveLength(0);
  });

  it("sends the complete label set and keeps label objects", async () => {
    const labels = [{ id: 3, name: "Later" }];
    const item = makeItem(1);
    seed(item);
    vi.mocked(api.updateItem).mockResolvedValueOnce({ ...item, labels });

    await enqueueItemMutation(
      item,
      {
        patch: { label_ids: [3] },
        labels,
      },
      context(),
    );

    expect(api.updateItem).toHaveBeenCalledWith(1, { label_ids: [3] });
    expect(cachedItem()?.labels).toEqual(labels);
  });

  it("updates counters optimistically and restores them on failure", async () => {
    const item = makeItem(1);
    seed(item);
    client.setQueryData<Counts>(["counts", "7"], {
      views: { all: 3, unread: 2, starred: 0 },
      feeds: { 7: 2 },
    });

    const request = deferred<Item>();
    vi.mocked(api.updateItem).mockReturnValueOnce(request.promise);

    const done = enqueueItemMutation(
      item,
      { patch: { starred: true } },
      context(),
    );
    expect(readCounts()?.views.starred).toBe(1);

    request.reject(new ApiError("The API refused that change.", 422));
    await done;

    expect(readCounts()).toEqual({
      views: { all: 3, unread: 2, starred: 0 },
      feeds: { 7: 2 },
    });
  });

  it("writes the confirmed item once the request settles", async () => {
    const item = makeItem(1);
    seed(item);
    const updated = applyIntent(item, {
      patch: { starred: true, is_read: true },
    });
    vi.mocked(api.updateItem).mockResolvedValueOnce(updated);

    await enqueueItemMutation(
      item,
      { patch: { starred: true } },
      context(),
    );

    expect(cachedItem()).toEqual(updated);
  });
});
