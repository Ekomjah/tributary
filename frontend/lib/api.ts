import axios, { type AxiosRequestConfig } from "axios";

import type {
  ArticleFetch,
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

const http = axios.create({
  baseURL: apiBase,
  headers: { Accept: "application/json" },
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function describeError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body: unknown = error.response?.data;

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

    if (error.response) {
      return `The API answered with ${error.response.status}.`;
    }

    return `Could not reach the Tributary API at ${apiBase}. Start it with "uv run tributary serve".`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Something went wrong.";
}

async function request<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    const response = await http.request<T>(config);
    if (response.status === 204) {
      return undefined as T;
    }
    return response.data;
  } catch (error) {
    if (axios.isCancel(error)) {
      throw error;
    }
    if (axios.isAxiosError(error)) {
      throw new ApiError(describeError(error), error.response?.status ?? 0);
    }
    throw error;
  }
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
    return request<Feed[]>({ url: "/api/feeds", signal });
  },

  createFeed(url: string): Promise<Feed> {
    return request<Feed>({
      url: "/api/feeds",
      method: "POST",
      data: { url },
    });
  },

  refreshFeed(feedId: number): Promise<FeedRefreshResult> {
    return request<FeedRefreshResult>({
      url: `/api/feeds/${feedId}/refresh`,
      method: "POST",
    });
  },

  refreshFeeds(): Promise<FeedRefreshResult[]> {
    return request<FeedRefreshResult[]>({
      url: "/api/feeds/refresh",
      method: "POST",
    });
  },

  listItems(query: ItemQuery = {}): Promise<ItemPage> {
    const params: Record<string, string | number | boolean> = {};
    if (query.unread !== undefined) {
      params.unread = query.unread;
    }
    if (query.starred !== undefined) {
      params.starred = query.starred;
    }
    if (query.feedId !== undefined && query.feedId !== null) {
      params.feed_id = query.feedId;
    }
    if (query.label) {
      params.label = query.label;
    }
    if (query.q) {
      params.q = query.q;
    }
    if (query.limit !== undefined) {
      params.limit = query.limit;
    }
    if (query.offset !== undefined) {
      params.offset = query.offset;
    }

    return request<ItemPage>({
      url: "/api/items",
      params,
      signal: query.signal,
    });
  },

  fetchItemArticle(itemId: number, force = false): Promise<ArticleFetch> {
    return request<ArticleFetch>({
      url: `/api/items/${itemId}/fetch`,
      method: "POST",
      params: force ? { force: true } : undefined,
    });
  },

  updateItem(itemId: number, update: ItemUpdate): Promise<Item> {
    return request<Item>({
      url: `/api/items/${itemId}`,
      method: "PATCH",
      data: update,
    });
  },

  listLabels(signal?: AbortSignal): Promise<Label[]> {
    return request<Label[]>({ url: "/api/labels", signal });
  },

  createLabel(name: string): Promise<Label> {
    return request<Label>({
      url: "/api/labels",
      method: "POST",
      data: { name },
    });
  },

  addItemLabel(itemId: number, labelId: number): Promise<Item> {
    return request<Item>({
      url: `/api/items/${itemId}/labels/${labelId}`,
      method: "POST",
    });
  },

  removeItemLabel(itemId: number, labelId: number): Promise<void> {
    return request<void>({
      url: `/api/items/${itemId}/labels/${labelId}`,
      method: "DELETE",
    });
  },
};
