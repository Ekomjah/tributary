export type Decision = "keep" | "drop";

export interface Label {
  id: number;
  name: string;
}

export type FeedKind = "feed" | "search" | "pipe";

export interface Feed {
  id: number;
  url: string;
  title: string;
  kind: FeedKind;
  pipe_id: number | null;
  last_fetched: string | null;
  last_error: string | null;
  created_at: string;
}

export interface FeedCandidate {
  url: string;
  title: string;
  kind: string;
}

export interface FeedDiscovery {
  input_url: string;
  page_title: string | null;
  candidates: FeedCandidate[];
}

export interface FeedAddResult {
  feed: Feed;
  result: FeedRefreshResult;
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
  content_html: string | null;
  author: string | null;
  cover_image: string | null;
  cover_image_alt: string | null;
  cover_caption: string | null;
  content_full: string | null;
  content_fetched_at: string | null;
  fetch_status: FetchStatus | null;
  source: string | null;
  is_read: boolean;
  starred: boolean;
  decision: Decision | null;
  fetched_at: string;
  labels: Label[];
  summary: string | null;
  why_care: string | null;
}

export interface ArticleFetch {
  id: number;
  content_html: string | null;
  author: string | null;
  cover_image: string | null;
  cover_image_alt: string | null;
  cover_caption: string | null;
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
  kind: FeedKind;
  new_items: number;
  total_entries: number;
  not_modified: boolean;
  error: string | null;
}

export interface PipeFeedResult {
  feed: Feed;
  created: boolean;
  items: number;
  seconds: number;
  error: string | null;
}

export type ItemView = "unread" | "all" | "starred";

export type SearchEngine = "google_news" | "google";
export type SearchFreshness = "day" | "week" | "month" | "year";

export interface FetchStep {
  box: "fetch";
  urls: string[];
}

export interface SearchStep {
  box: "search";
  query: string;
  engine?: SearchEngine;
  gl?: string;
  hl?: string;
  freshness?: SearchFreshness | null;
  max_results?: number;
  refine?: boolean;
}

export interface MergeStep {
  box: "merge";
}

export interface DedupeStep {
  box: "dedupe";
  by?: "link" | "guid" | "title";
}

export interface FilterStep {
  box: "filter";
  keyword: string;
  fields?: Array<"title" | "content" | "link">;
}

export interface SortStep {
  box: "sort";
  by?: "published" | "fetched_at" | "title";
  order?: "asc" | "desc";
}

export interface LimitStep {
  box: "limit";
  count?: number;
}

export interface FullTextStep {
  box: "fulltext";
}

export interface SummarizeStep {
  box: "summarize";
}

export interface MeaningStep {
  box: "meaning";
  criterion: string;
}

export interface WhyCareStep {
  box: "whycare";
}

export type PipeStep =
  | FetchStep
  | SearchStep
  | MergeStep
  | DedupeStep
  | FilterStep
  | SortStep
  | LimitStep
  | FullTextStep
  | SummarizeStep
  | MeaningStep
  | WhyCareStep;

export interface PipeSpec {
  name: string;
  steps: PipeStep[];
}

export interface Pipe {
  id: number;
  name: string;
  spec_json: PipeSpec;
  created_at: string;
  updated_at: string;
}

export interface BoxRun {
  box: string;
  seconds: number;
  items_in: number;
  items_out: number;
  status: "success" | "error";
  error: string | null;
}

export interface PipeRunRecord {
  id: number;
  pipe_id: number;
  started: string;
  seconds: number | null;
  status: "running" | "success" | "error";
  error: string | null;
  error_step: number | null;
  error_box: string | null;
  result_count: number;
}

export interface PipeRun {
  run: PipeRunRecord;
  items: Item[];
  steps: BoxRun[];
}

export interface SearchRefinement {
  spec: {
    q: string;
    engine: SearchEngine;
    gl: string;
    hl: string;
    freshness: SearchFreshness | null;
    max_results: number;
  };
  fallback: boolean;
  model: string;
  seconds: number;
}
