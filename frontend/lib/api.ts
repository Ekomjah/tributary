import type {
  Feed,
  FeedRefreshResult,
  Item,
  ItemPage,
  ItemUpdate,
  Label,
} from "./types";

const DEFAULT_API_BASE = "http://127.0.0.1:8000";

export const apiBase = (
  process.env.NEXT_PUBLIC_API_BASE ?? DEFAULT_API_BASE
).replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function describeError(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (isRecord(body)) {
      const detail = body.detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail)) {
        const messages = detail
          .map((entry) =>
            isRecord(entry) && typeof entry.msg === "string" ? entry.msg : null,
          )
          .filter((message): message is string => message !== null);
        if (messages.length > 0) {
          return messages.join(". ");
        }
      }
    }
  } catch {
    // The body was empty or not JSON; fall back to the status code.
  }

  return `The API answered with ${response.status}.`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      `Could not reach the Tributary API at ${apiBase}. Start it with "uv run tributary serve".`,
      0,
    );
  }

  if (!response.ok) {
    throw new ApiError(await describeError(response), response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export interface ItemQuery {
  unread?: boolean;
  starred?: boolean;
  feedId?: number | null;
  label?: string | null;
  q?: string | null;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

export const api = {
  listFeeds(signal?: AbortSignal): Promise<Feed[]> {
    return request<Feed[]>("/api/feeds", { signal });
  },

  createFeed(url: string): Promise<Feed> {
    return request<Feed>("/api/feeds", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  },

  refreshFeed(feedId: number): Promise<FeedRefreshResult> {
    return request<FeedRefreshResult>(`/api/feeds/${feedId}/refresh`, {
      method: "POST",
    });
  },

  refreshFeeds(): Promise<FeedRefreshResult[]> {
    return request<FeedRefreshResult[]>("/api/feeds/refresh", {
      method: "POST",
    });
  },

  listItems(query: ItemQuery = {}): Promise<ItemPage> {
    const params = new URLSearchParams();
    if (query.unread !== undefined) {
      params.set("unread", String(query.unread));
    }
    if (query.starred !== undefined) {
      params.set("starred", String(query.starred));
    }
    if (query.feedId !== undefined && query.feedId !== null) {
      params.set("feed_id", String(query.feedId));
    }
    if (query.label) {
      params.set("label", query.label);
    }
    if (query.q) {
      params.set("q", query.q);
    }
    if (query.limit !== undefined) {
      params.set("limit", String(query.limit));
    }
    if (query.offset !== undefined) {
      params.set("offset", String(query.offset));
    }

    const suffix = params.toString();
    return request<ItemPage>(`/api/items${suffix ? `?${suffix}` : ""}`, {
      signal: query.signal,
    });
  },

  updateItem(itemId: number, update: ItemUpdate): Promise<Item> {
    return request<Item>(`/api/items/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(update),
    });
  },

  listLabels(signal?: AbortSignal): Promise<Label[]> {
    return request<Label[]>("/api/labels", { signal });
  },

  createLabel(name: string): Promise<Label> {
    return request<Label>("/api/labels", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  },

  addItemLabel(itemId: number, labelId: number): Promise<Item> {
    return request<Item>(`/api/items/${itemId}/labels/${labelId}`, {
      method: "POST",
    });
  },

  removeItemLabel(itemId: number, labelId: number): Promise<void> {
    return request<void>(`/api/items/${itemId}/labels/${labelId}`, {
      method: "DELETE",
    });
  },
};
