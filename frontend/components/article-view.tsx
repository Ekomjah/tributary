"use client";

import { useEffect, useRef } from "react";
import {
  ArrowLeft,
  Circle,
  CircleCheck,
  ExternalLink,
  Loader2,
  Share2,
  Sparkles,
  Star,
  Tag,
} from "lucide-react";

import ArticleBody from "@/components/article-body";
import LabelMenu from "@/components/label-menu";
import { Button } from "@/components/ui/button";
import { formatFullDate, plainText, readingMinutes } from "@/lib/text";
import type { Decision, Item, Label } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ArticleViewProps {
  item: Item;
  feedName: string;
  feedCount: number;
  labels: Label[];
  contextLabel: string;
  fetching: boolean;
  pendingTitle: string | null;
  focusItemId: number | null;
  onBack: () => void;
  onToggleStar: (item: Item) => void;
  onToggleRead: (item: Item) => void;
  onToggleDecision: (item: Item, decision: Decision) => void;
  onToggleLabel: (item: Item, label: Label) => void;
  onSelectFeed: (feedId: number) => void;
  onShare?: (item: Item) => void;
}

export default function ArticleView({
  item,
  feedName,
  feedCount,
  labels,
  contextLabel,
  fetching,
  pendingTitle,
  focusItemId,
  onBack,
  onToggleStar,
  onToggleRead,
  onToggleDecision,
  onToggleLabel,
  onSelectFeed,
  onShare,
}: ArticleViewProps) {
  const text = item.content_full ?? item.content;
  const readingTime = readingMinutes(plainText(text));
  const published = item.published ?? item.fetched_at;
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusItemId !== null && focusItemId === item.id) {
      headingRef.current?.focus();
    }
  }, [focusItemId, item.id]);

  return (
    <div className="mx-auto w-full max-w-[780px] px-6 py-5 max-[700px]:px-4">
      <div className="flex items-center justify-between gap-3 border-b border-divider pb-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="-ml-2 gap-1.5 px-2 text-[12px]"
          onClick={onBack}
        >
          <ArrowLeft className="size-3.5" />
          Back to {contextLabel}
        </Button>
        <span className="hidden font-mono text-[10px] text-faint sm:inline">
          Esc
        </span>
      </div>

      {pendingTitle && (
        <div
          role="status"
          aria-live="polite"
          className="mt-2 flex items-center gap-1.5 text-[11px] text-muted"
        >
          <Loader2
            className="size-3 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
          <span className="truncate">Opening “{pendingTitle}”…</span>
        </div>
      )}

      <article className="pt-5" aria-busy={pendingTitle ? true : undefined}>
        <header>
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="font-reading text-[26px] font-bold leading-[1.22] text-accent text-balance focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent max-[700px]:text-[23px]"
          >
            {item.link ? (
              <a
                href={item.link}
                target="_blank"
                rel="noreferrer"
                className="hover:text-accent-dark hover:underline"
              >
                {item.title || "Untitled"}
              </a>
            ) : (
              item.title || "Untitled"
            )}
          </h1>

          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-divider pb-3 text-[11px] text-faint">
            <button
              type="button"
              onClick={() => onSelectFeed(item.feed_id)}
              className="font-bold text-accent hover:text-accent-dark hover:underline"
            >
              {feedName}
            </button>
            {feedCount > 0 && <span>({feedCount})</span>}
            <span aria-hidden="true">·</span>
            <time dateTime={published}>{formatFullDate(published)}</time>
            {item.shared_by && (
              <>
                <span aria-hidden="true">·</span>
                <span className="text-muted">
                  Shared by {item.shared_by}
                  {item.origin_feed_title
                    ? ` from ${item.origin_feed_title}`
                    : ""}
                </span>
              </>
            )}
            {item.author && (
              <>
                <span aria-hidden="true">·</span>
                <span className="text-muted">By {item.author}</span>
              </>
            )}
            {readingTime > 0 && (
              <>
                <span aria-hidden="true">·</span>
                <span>{readingTime} min read</span>
              </>
            )}
            {item.labels.length > 0 && (
              <span className="flex flex-wrap items-center gap-1">
                {item.labels.map((entry) => (
                  <span
                    key={entry.id}
                    className="inline-flex items-center gap-1 rounded-sm border border-line bg-chrome px-1.5 py-0.5 text-[10px] text-muted"
                  >
                    <Tag className="size-2.5" aria-hidden="true" />
                    {entry.name}
                  </span>
                ))}
              </span>
            )}
          </div>
        </header>

        <div className="my-3 flex flex-wrap items-center gap-1.5">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className={cn(item.starred && "text-star")}
            onClick={() => onToggleStar(item)}
            aria-pressed={item.starred}
          >
            <Star
              className="size-3.5"
              fill={item.starred ? "currentColor" : "none"}
            />
            {item.starred ? "Starred" : "Star"}
          </Button>

          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onToggleRead(item)}
          >
            {item.is_read ? (
              <CircleCheck className="size-3.5" />
            ) : (
              <Circle className="size-3.5" />
            )}
            {item.is_read ? "Mark unread" : "Mark read"}
          </Button>

          <LabelMenu
            labels={labels}
            selected={item.labels}
            onToggle={(entry) => onToggleLabel(item, entry)}
            triggerClassName="size-7 border border-line bg-chrome text-ink hover:bg-[#e8e8e8]"
          />

          {onShare && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onShare(item)}
            >
              <Share2 className="size-3.5" />
              Share
            </Button>
          )}

          {item.link && (
            <Button
              variant="outline"
              size="sm"
              nativeButton={false}
              render={
                <a href={item.link} target="_blank" rel="noreferrer" />
              }
            >
              <ExternalLink className="size-3.5" />
              Open original
            </Button>
          )}
        </div>

        <ArticleBody item={item} fetching={fetching} />

        <div className="mt-10 border-t border-divider pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold uppercase tracking-[0.06em] text-muted">
              Your taste
            </span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className={cn(
                item.decision === "keep" &&
                  "border-accent bg-accent-bg font-bold",
              )}
              onClick={() => onToggleDecision(item, "keep")}
              aria-pressed={item.decision === "keep"}
            >
              Keep
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className={cn(
                item.decision === "drop" &&
                  "border-accent bg-accent-bg font-bold",
              )}
              onClick={() => onToggleDecision(item, "drop")}
              aria-pressed={item.decision === "drop"}
            >
              Drop
            </Button>
          </div>
          <p className="mt-2 flex items-center gap-1.5 text-[11px] text-faint">
            <Sparkles className="size-3.5" aria-hidden="true" />
            A local training signal. Nothing leaves this machine.
          </p>
        </div>

        <p className="mt-6 font-mono text-[10px] text-faint">
          j / k next · previous · Esc back
        </p>
      </article>
    </div>
  );
}
