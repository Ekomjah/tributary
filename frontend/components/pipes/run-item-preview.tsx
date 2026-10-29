"use client";

import { useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  Loader2,
  TriangleAlert,
} from "lucide-react";

import ArticleBody from "@/components/article-body";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { articleHref, type FeedsScope } from "@/lib/feeds";
import { withArticle } from "@/lib/pipes";
import { formatRelative, hostOf, plainText, readingMinutes } from "@/lib/text";
import type { Item } from "@/lib/types";

const READER_SCOPE: FeedsScope = {
  view: "all",
  feedId: null,
  label: null,
  query: "",
};

function messageOf(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Could not fetch the full text.";
}

interface RunItemPreviewProps {
  items: Item[];
  index: number | null;
  onIndexChange: (index: number | null) => void;
  onItemChange: (item: Item) => void;
}

export default function RunItemPreview({
  items,
  index,
  onIndexChange,
  onItemChange,
}: RunItemPreviewProps) {
  const item = index === null ? null : (items[index] ?? null);
  const currentIndex = index ?? 0;
  const [fetchingId, setFetchingId] = useState<number | null>(null);
  const [fetchError, setFetchError] = useState<{
    id: number;
    message: string;
  } | null>(null);

  const fetching = item !== null && fetchingId === item.id;
  const error =
    item !== null && fetchError?.id === item.id ? fetchError.message : null;
  const needsText = item !== null && item.content_full === null;
  const text = item ? (item.content_full ?? item.content) : "";
  const readingTime = item ? readingMinutes(plainText(text)) : 0;

  async function fetchFullText() {
    if (!item || fetchingId !== null) {
      return;
    }

    const id = item.id;
    const retry = item.fetch_status !== null;
    setFetchingId(id);
    setFetchError(null);
    try {
      const article = await api.fetchItemArticle(id, retry);
      onItemChange(withArticle(item, article));
    } catch (caught) {
      setFetchError({ id, message: messageOf(caught) });
    } finally {
      setFetchingId((current) => (current === id ? null : current));
    }
  }

  return (
    <Dialog
      open={item !== null}
      onOpenChange={(next) => {
        if (!next) {
          onIndexChange(null);
        }
      }}
    >
      <DialogContent className="flex max-h-[88vh] max-w-[820px] flex-col gap-0 p-0">
        {item && (
          <>
            <DialogHeader className="block shrink-0 py-3">
              <DialogTitle className="pr-2 text-[17px] leading-snug">
                {item.title || "Untitled"}
              </DialogTitle>
              <DialogDescription className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                <span>
                  {item.source ||
                    (item.link ? hostOf(item.link) : "Search result")}
                </span>
                <span aria-hidden="true">·</span>
                <span>
                  {formatRelative(item.published ?? item.fetched_at)}
                </span>
                {item.author && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="text-muted">By {item.author}</span>
                  </>
                )}
                {item.author && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>By {item.author}</span>
                  </>
                )}
                {readingTime > 0 && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>{readingTime} min read</span>
                  </>
                )}
              </DialogDescription>

              <div className="mt-2 flex flex-wrap items-center gap-1">
                {item.content_full && <PreviewBadge>Full text</PreviewBadge>}
                {item.fetch_status && item.fetch_status !== "ok" && (
                  <PreviewBadge>Full text failed</PreviewBadge>
                )}
                {item.summary && <PreviewBadge>Summary</PreviewBadge>}
                {item.why_care && <PreviewBadge>Why you’d care</PreviewBadge>}
                {item.is_read && <PreviewBadge>Read</PreviewBadge>}
                {item.starred && <PreviewBadge>Starred</PreviewBadge>}
              </div>
            </DialogHeader>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {needsText && (
                <div className="mb-4 flex flex-wrap items-center gap-2 border border-line bg-chrome px-3 py-2">
                  <p className="min-w-0 flex-1 text-[12px] leading-4 text-muted">
                    {item.fetch_status === null
                      ? "This result only has the feed excerpt. Fetch the article to read it here."
                      : "The full text could not be fetched last time. Try it again."}
                  </p>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => void fetchFullText()}
                    disabled={fetchingId !== null}
                  >
                    {fetching ? (
                      <Loader2 className="animate-spin" aria-hidden="true" />
                    ) : (
                      <FileText aria-hidden="true" />
                    )}
                    {fetching
                      ? "Fetching…"
                      : item.fetch_status === null
                        ? "Fetch full text"
                        : "Try again"}
                  </Button>
                </div>
              )}

              {error && (
                <p
                  role="alert"
                  className="mb-3 flex items-start gap-1.5 text-[12px] leading-5 text-danger"
                >
                  <TriangleAlert
                    className="mt-0.5 size-3.5 shrink-0"
                    aria-hidden="true"
                  />
                  {error}
                </p>
              )}

              <ArticleBody item={item} fetching={fetching} />
            </div>

            <DialogFooter className="shrink-0 items-center sm:justify-between">
              <div className="flex items-center justify-center gap-1">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={currentIndex === 0}
                  onClick={() => onIndexChange(currentIndex - 1)}
                >
                  <ChevronLeft aria-hidden="true" />
                  Previous
                </Button>
                <span className="px-1 font-mono text-[10px] text-faint">
                  {currentIndex + 1} / {items.length}
                </span>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={currentIndex >= items.length - 1}
                  onClick={() => onIndexChange(currentIndex + 1)}
                >
                  Next
                  <ChevronRight aria-hidden="true" />
                </Button>
              </div>

              <div className="flex items-center justify-center gap-1.5">
                {item.link && (
                  <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={
                      <a
                        href={item.link}
                        target="_blank"
                        rel="noopener noreferrer"
                      />
                    }
                  >
                    <ExternalLink aria-hidden="true" />
                    Original
                  </Button>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  nativeButton={false}
                  render={<Link href={articleHref(item, READER_SCOPE)} />}
                >
                  <BookOpen aria-hidden="true" />
                  Read in reader
                </Button>
              </div>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function PreviewBadge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-sm border border-line bg-chrome px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.04em] text-muted">
      {children}
    </span>
  );
}
