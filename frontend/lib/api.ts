import axios, { type AxiosRequestConfig } from "axios";

import type {
  ArticleFetch,
  Feed,
  FeedAddResult,
  FeedDiscovery,
  FeedRefreshResult,
  Item,
  ItemPage,
  ItemUpdate,
  Label,
  Pipe,
  PipeFeedResult,
  PipeRun,
  PipeRunRecord,
  PipeSpec,
  SearchRefinement,
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

  discoverFeeds(url: string): Promise<FeedDiscovery> {
    return request<FeedDiscovery>({
      url: "/api/feeds/discover",
      method: "POST",
      data: { url },
    });
  },

  createFeed(url: string): Promise<FeedAddResult> {
    return request<FeedAddResult>({
      url: "/api/feeds",
      method: "POST",
      data: { url },
    });
  },

  deleteFeed(feedId: number): Promise<void> {
    return request<void>({
      url: `/api/feeds/${feedId}`,
      method: "DELETE",
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

  addPipeFeed(pipeId: number): Promise<PipeFeedResult> {
    return request<PipeFeedResult>({
      url: "/api/feeds/pipe",
      method: "POST",
      data: { pipe_id: pipeId },
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

  getItem(itemId: number, signal?: AbortSignal): Promise<Item> {
    return request<Item>({
      url: `/api/items/${itemId}`,
      signal,
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

  listPipes(signal?: AbortSignal): Promise<Pipe[]> {
    return request<Pipe[]>({ url: "/api/pipes", signal });
  },

  getPipe(pipeId: number, signal?: AbortSignal): Promise<Pipe> {
    return request<Pipe>({ url: `/api/pipes/${pipeId}`, signal });
  },

  createPipe(name: string, spec: PipeSpec): Promise<Pipe> {
    return request<Pipe>({
      url: "/api/pipes",
      method: "POST",
      data: { name, spec_json: spec },
    });
  },

  updatePipe(
    pipeId: number,
    update: { name?: string; spec_json?: PipeSpec },
  ): Promise<Pipe> {
    return request<Pipe>({
      url: `/api/pipes/${pipeId}`,
      method: "PATCH",
      data: update,
    });
  },

  deletePipe(pipeId: number): Promise<void> {
    return request<void>({
      url: `/api/pipes/${pipeId}`,
      method: "DELETE",
    });
  },

  startPipeRun(pipeId: number): Promise<PipeRunRecord> {
    return request<PipeRunRecord>({
      url: `/api/pipes/${pipeId}/runs`,
      method: "POST",
    });
  },

  getRun(runId: number): Promise<PipeRunRecord> {
    return request<PipeRunRecord>({
      url: `/api/runs/${runId}`,
    });
  },

  listPipeRuns(
    pipeId: number,
    limit = 20,
    signal?: AbortSignal,
  ): Promise<PipeRunRecord[]> {
    return request<PipeRunRecord[]>({
      url: "/api/runs",
      params: { pipe_id: pipeId, limit },
      signal,
    });
  },

  getPipeRun(runId: number): Promise<PipeRun> {
    return request<PipeRun>({
      url: `/api/runs/${runId}/results`,
    });
  },

  refineSearch(query: string): Promise<SearchRefinement> {
    return request<SearchRefinement>({
      url: "/api/search/refine",
      method: "POST",
      data: { query },
    });
  },
};
