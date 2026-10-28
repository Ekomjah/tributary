export type Decision = "keep" | "drop";

export interface Label {
  id: number;
  name: string;
}

export interface Feed {
  id: number;
  url: string;
  title: string;
  last_fetched: string | null;
  last_error: string | null;
  created_at: string;
}

export type FetchStatus = "ok" | "empty" | "blocked" | "error";

export interface Item {
  id: number;
  feed_id: number;
  guid: string;
  title: string;
  link: string | null;
  published: string | null;
  content: string;
  content_full: string | null;
  content_fetched_at: string | null;
  fetch_status: FetchStatus | null;
  is_read: boolean;
  starred: boolean;
  decision: Decision | null;
  fetched_at: string;
  labels: Label[];
  summary: string | null;
}

export interface ArticleFetch {
  id: number;
  content_full: string | null;
  content_fetched_at: string | null;
  fetch_status: FetchStatus | null;
}

export interface ItemPage {
  items: Item[];
  total: number;
  limit: number;
  offset: number;
}

export interface ItemUpdate {
  is_read?: boolean;
  starred?: boolean;
  decision?: Decision | null;
  label_ids?: number[];
}

export interface FeedRefreshResult {
  url: string;
  feed_id: number | null;
  title: string;
  new_items: number;
  total_entries: number;
  not_modified: boolean;
  error: string | null;
}

export type ItemView = "unread" | "all" | "starred";
