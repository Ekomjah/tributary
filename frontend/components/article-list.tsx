import {
  Circle,
  CircleCheck,
  ExternalLink,
  Loader2,
  Plus,
  Rss,
  Star,
  Tag,
} from "lucide-react";

import LabelMenu from "@/components/label-menu";
import { Button } from "@/components/ui/button";
import { excerpt, formatRelative } from "@/lib/text";
import type { Item, ItemView, Label } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ArticleListProps {
  items: Item[];
  total: number;
  loading: boolean;
  heading: string;
  query: string;
  view: ItemView;
  hasFeeds: boolean;
  hasFilters: boolean;
  feedNames: Map<number, string>;
  feedCounts: Record<number, number>;
  labels: Label[];
  selectedId: number | null;
  onOpen: (item: Item) => void;
  onToggleStar: (item: Item) => void;
  onToggleRead: (item: Item) => void;
  onToggleLabel: (item: Item, label: Label) => void;
  onSelectFeed: (feedId: number) => void;
  onSelectView: (view: ItemView) => void;
  onAddFeed: () => void;
  onClearSearch: () => void;
}

function EmptyState({
  query,
  view,
  hasFeeds,
  hasFilters,
  onAddFeed,
  onSelectView,
  onClearSearch,
}: Pick<
  ArticleListProps,
  | "query"
  | "view"
  | "hasFeeds"
  | "hasFilters"
  | "onAddFeed"
  | "onSelectView"
  | "onClearSearch"
>) {
  if (query) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
        <p className="text-[15px] font-bold text-ink">
          No items match “{query}”
        </p>
        <p className="mt-1 max-w-sm text-[13px] leading-5 text-muted">
          Try a broader word, or search across all items instead of just this
          view.
        </p>
        <Button
          type="button"
          variant="link"
          className="mt-3 text-[13px]"
          onClick={onClearSearch}
        >
          Clear search
        </Button>
      </div>
    );
  }

  if (!hasFeeds) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
        <Rss className="size-6 text-faint" aria-hidden="true" />
        <p className="mt-3 text-[15px] font-bold text-ink">No feeds yet</p>
        <p className="mt-1 max-w-sm text-[13px] leading-5 text-muted">
          Paste any RSS or Atom URL. Tributary stores it locally and never asks
          for an account.
        </p>
        <Button
          type="button"
          variant="primary"
          className="mt-4"
          onClick={onAddFeed}
        >
          <Plus />
          Add feed
        </Button>
      </div>
    );
  }

  if (view === "unread" && !hasFilters) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
        <CircleCheck className="size-6 text-success" aria-hidden="true" />
        <p className="mt-3 text-[15px] font-bold text-ink">
          You’re all caught up
        </p>
        <p className="mt-1 text-[13px] text-muted">
          Nothing unread in this view.
        </p>
        <Button
          type="button"
          variant="link"
          className="mt-3 text-[13px]"
          onClick={() => onSelectView("all")}
        >
          View all items
        </Button>
      </div>
    );
  }

  if (view === "starred") {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
        <Star className="size-6 text-faint" aria-hidden="true" />
        <p className="mt-3 text-[15px] font-bold text-ink">
          No starred items yet
        </p>
        <p className="mt-1 text-[13px] text-muted">
          Star a story and it will wait for you here.
        </p>
        <Button
          type="button"
          variant="link"
          className="mt-3 text-[13px]"
          onClick={() => onSelectView("all")}
        >
          View all items
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
      <p className="text-[15px] font-bold text-ink">Nothing here yet</p>
      <p className="mt-1 text-[13px] text-muted">
        Change the filter, or refresh the feeds to look for new stories.
      </p>
      <Button
        type="button"
        variant="link"
        className="mt-3 text-[13px]"
        onClick={() => onSelectView("all")}
      >
        View all items
      </Button>
    </div>
  );
}

export default function ArticleList({
  items,
  total,
  loading,
  heading,
  query,
  view,
  hasFeeds,
  hasFilters,
  feedNames,
  feedCounts,
  labels,
  selectedId,
  onOpen,
  onToggleStar,
  onToggleRead,
  onToggleLabel,
  onSelectFeed,
  onSelectView,
  onAddFeed,
  onClearSearch,
}: ArticleListProps) {
  return (
    <div className="mx-auto w-full max-w-[780px] px-6 py-5 max-[700px]:px-4">
      <div className="flex min-h-8 items-baseline justify-between gap-3 border-b border-divider pb-3">
        <h1 className="text-[20px] font-bold leading-tight text-ink">
          {heading}{" "}
          {!loading && (
            <span className="font-normal text-faint">({total})</span>
          )}
        </h1>
        {loading && (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-muted">
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            Loading…
          </span>
        )}
      </div>

      {loading && items.length === 0 ? (
        <div className="divide-y divide-divider" aria-hidden="true">
          {[0, 1, 2, 3, 4].map((row) => (
            <div className="py-4" key={row}>
              <div className="h-4 w-3/5 bg-chrome" />
              <div className="mt-2 h-3 w-4/5 bg-chrome" />
              <div className="mt-2 h-3 w-1/3 bg-chrome" />
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          query={query}
          view={view}
          hasFeeds={hasFeeds}
          hasFilters={hasFilters}
          onAddFeed={onAddFeed}
          onSelectView={onSelectView}
          onClearSearch={onClearSearch}
        />
      ) : (
        <div className="divide-y divide-divider">
          {items.map((item) => {
            const preview = item.summary ?? excerpt(item.content, 190);
            const selected = selectedId === item.id;

            return (
              <article
                key={item.id}
                id={`item-${item.id}`}
                onClick={() => onOpen(item)}
                className={cn(
                  "group cursor-pointer border-l-[3px] py-4 pl-3 pr-1 transition-colors duration-100 hover:bg-[#fafafa]",
                  selected
                    ? "border-accent bg-[#f8fbff]"
                    : "border-transparent",
                )}
              >
                <div className="flex items-start gap-3">
                  <h2 className="min-w-0 flex-1">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpen(item);
                      }}
                      className={cn(
                        "block w-full truncate text-left text-[15px] font-bold leading-snug hover:underline",
                        item.is_read ? "text-muted" : "text-accent",
                      )}
                    >
                      {item.title || "Untitled"}
                    </button>
                  </h2>

                  <div
                    className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity duration-100 group-focus-within:opacity-100 group-hover:opacity-100 max-[700px]:opacity-100"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <Button
                      type="button"
                      variant="icon"
                      size="icon-sm"
                      className={cn(
                        item.starred
                          ? "text-star hover:text-star"
                          : "text-faint hover:text-ink",
                      )}
                      onClick={() => onToggleStar(item)}
                      aria-label={item.starred ? "Unstar item" : "Star item"}
                      aria-pressed={item.starred}
                      title={item.starred ? "Unstar" : "Star"}
                    >
                      <Star
                        className="size-3.5"
                        fill={item.starred ? "currentColor" : "none"}
                      />
                    </Button>

                    <Button
                      type="button"
                      variant="icon"
                      size="icon-sm"
                      className={cn(
                        item.is_read ? "text-muted" : "text-faint",
                      )}
                      onClick={() => onToggleRead(item)}
                      aria-label={
                        item.is_read ? "Mark item unread" : "Mark item read"
                      }
                      title={item.is_read ? "Mark unread" : "Mark read"}
                    >
                      {item.is_read ? (
                        <CircleCheck className="size-3.5" />
                      ) : (
                        <Circle className="size-3.5" />
                      )}
                    </Button>

                    <LabelMenu
                      labels={labels}
                      selected={item.labels}
                      onToggle={(entry) => onToggleLabel(item, entry)}
                    />

                    {item.link && (
                      <Button
                        variant="icon"
                        size="icon-sm"
                        nativeButton={false}
                        className="text-faint hover:text-ink"
                        render={
                          <a
                            href={item.link}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(event) => event.stopPropagation()}
                          />
                        }
                        aria-label="Open original article"
                        title="Open original"
                      >
                        <ExternalLink className="size-3.5" />
                      </Button>
                    )}
                  </div>
                </div>

                <p className="mt-1 truncate text-[12px] leading-5 text-muted">
                  {item.summary ? (
                    <>
                      <span className="font-bold text-ink">Summary:</span>{" "}
                      {preview}
                    </>
                  ) : (
                    preview || "No preview from this feed."
                  )}
                </p>

                <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-faint">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelectFeed(item.feed_id);
                    }}
                    className="text-accent hover:text-accent-dark hover:underline"
                  >
                    See more from {feedNames.get(item.feed_id) ?? "Unknown feed"}
                    {(feedCounts[item.feed_id] ?? 0) > 0
                      ? ` (${feedCounts[item.feed_id]})`
                      : ""}
                  </button>
                  <span aria-hidden="true">·</span>
                  <time dateTime={item.published ?? item.fetched_at}>
                    {formatRelative(item.published ?? item.fetched_at)}
                  </time>
                  {item.labels.length > 0 && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span className="inline-flex items-center gap-1">
                        <Tag className="size-3" aria-hidden="true" />
                        {item.labels.map((entry) => entry.name).join(", ")}
                      </span>
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
