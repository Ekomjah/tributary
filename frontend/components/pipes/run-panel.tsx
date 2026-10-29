"use client";

import { useMemo, useState } from "react";
import {
  BookOpen,
  CircleCheck,
  Clock,
  ExternalLink,
  Loader2,
  TriangleAlert,
  X,
} from "lucide-react";

import { HashtagText } from "@/components/article-body";
import { Button } from "@/components/ui/button";
import { stepHint } from "@/lib/pipes";
import { excerpt, formatRelative, hostOf } from "@/lib/text";
import type { Item, PipeRun } from "@/lib/types";
import { cn } from "@/lib/utils";

import RunItemPreview from "./run-item-preview";

interface RunPanelProps {
  result: PipeRun | null;
  error: string | null;
  running: boolean;
  onClose: () => void;
}

const PAGE_SIZE = 20;

export default function RunPanel({
  result,
  error,
  running,
  onClose,
}: RunPanelProps) {
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [overrides, setOverrides] = useState<Record<number, Item>>({});

  const items = useMemo(
    () =>
      result ? result.items.map((item) => overrides[item.id] ?? item) : [],
    [overrides, result],
  );
  const shown = items.slice(0, visible);
  const fullTextCount = items.filter(
    (item) => item.content_full !== null,
  ).length;
  const aiCount = items.filter(
    (item) => Boolean(item.summary) || Boolean(item.why_care),
  ).length;

  if (!running && !result && !error) {
    return null;
  }

  return (
    <>
      <aside className="flex w-[340px] shrink-0 flex-col border-l border-divider bg-canvas max-[900px]:w-full max-[900px]:border-l-0 max-[900px]:border-t">
        <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-divider bg-chrome px-3">
          <div
            className="flex min-w-0 items-center gap-1.5"
            role="status"
            aria-live="polite"
          >
            {running ? (
              <Loader2 className="size-3.5 animate-spin text-accent" />
            ) : error ? (
              <TriangleAlert className="size-3.5 text-danger" />
            ) : (
              <CircleCheck className="size-3.5 text-success" />
            )}
            <h2 className="truncate text-[12px] font-bold">
              {running
                ? "Running…"
                : error
                  ? result?.run.error_box
                    ? `Failed at ${result.run.error_box}`
                    : "Run failed"
                  : "Results"}
            </h2>
          </div>
          <Button
            type="button"
            variant="icon"
            size="icon-xs"
            onClick={onClose}
            aria-label="Close results"
          >
            <X className="size-3.5" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {running && (
            <p className="text-[12px] leading-5 text-muted">
              Fetching, searching and shaping the stream. This can take a few
              seconds per feed.
            </p>
          )}

          {error && (
            <p
              role="alert"
              className="flex items-start gap-2 text-[12px] leading-5 text-danger"
            >
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
              {error}
            </p>
          )}

          {result && !running && (
            <>
              <p className="text-[12px] leading-5 text-muted">
                <strong className="text-ink">{items.length}</strong> item
                {items.length === 1 ? "" : "s"} in{" "}
                <strong className="text-ink">
                  {(result.run.seconds ?? 0).toFixed(2)}s
                </strong>
                {" · "}
                <strong className="text-ink">{fullTextCount}</strong> with full
                text
                {aiCount > 0 && (
                  <>
                    {" · "}
                    <strong className="text-ink">{aiCount}</strong> with AI notes
                  </>
                )}
              </p>

              <p className="mt-1 font-mono text-[10px] text-faint">
                Run #{result.run.id} · {formatRelative(result.run.started)}
              </p>

              <div className="mt-3 border-y border-divider">
                {result.steps.map((step, index) => {
                  const slow = step.seconds > 2;
                  const failed = step.status === "error";
                  const hint = stepHint(step);
                  return (
                    <div
                      key={`${step.box}-${index}`}
                      className="flex items-center gap-2 border-b border-divider py-1.5 text-[11px] last:border-b-0"
                    >
                      <span className="w-4 shrink-0 font-mono text-faint">
                        {index + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div
                          className={cn(
                            "flex items-center gap-1 truncate font-bold",
                            failed && "text-danger",
                          )}
                        >
                          {failed && (
                            <TriangleAlert
                              className="size-3 shrink-0"
                              aria-hidden="true"
                            />
                          )}
                          {step.box}
                        </div>
                        {hint && !failed && (
                          <div className="truncate text-[10px] text-faint">
                            {hint}
                          </div>
                        )}
                        {failed && step.error && (
                          <div className="mt-0.5 line-clamp-2 text-[10px] leading-4 text-danger">
                            {step.error}
                          </div>
                        )}
                      </div>
                      <span
                        className="shrink-0 font-mono text-faint"
                        title={`${step.items_in} in, ${step.items_out} out`}
                      >
                        {step.items_in} → {step.items_out}
                      </span>
                      <span
                        className={cn(
                          "flex w-14 shrink-0 items-center justify-end gap-1 font-mono",
                          failed
                            ? "text-danger"
                            : slow
                              ? "text-warn"
                              : "text-muted",
                        )}
                      >
                        {!failed && slow && <Clock className="size-3" />}
                        {step.seconds.toFixed(2)}s
                      </span>
                    </div>
                  );
                })}
              </div>

              {items.length === 0 ? (
                <p className="mt-4 text-[12px] leading-5 text-muted">
                  No items. Check the source boxes and filters.
                </p>
              ) : (
                <>
                  <div className="mt-3 space-y-3">
                    {shown.map((item, index) => {
                      const key =
                        item.guid || item.link || `${item.title}-${index}`;
                      const source =
                        item.source ||
                        (item.link ? hostOf(item.link) : "Search result");
                      const body = item.content_full ?? item.content;
                      const hasFullText = item.content_full !== null;
                      const fetchFailed =
                        item.fetch_status !== null &&
                        item.fetch_status !== "ok";
                      return (
                        <article
                          key={key}
                          className="border-b border-divider pb-3 last:border-b-0"
                        >
                          <div className="flex items-start gap-1.5">
                            <button
                              type="button"
                              onClick={() => setPreviewIndex(index)}
                              className="min-w-0 flex-1 text-left text-[13px] font-bold leading-5 text-accent hover:underline"
                            >
                              {item.title || item.link || "Untitled"}
                            </button>
                            {item.link && (
                              <a
                                href={item.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label="Open original"
                                title="Open original"
                                className="mt-0.5 shrink-0 text-faint hover:text-ink"
                              >
                                <ExternalLink className="size-3" />
                              </a>
                            )}
                          </div>
                          <p className="mt-0.5 text-[10px] text-faint">
                            {source} ·{" "}
                            {formatRelative(item.published ?? item.fetched_at)}
                          </p>

                          {(hasFullText ||
                            fetchFailed ||
                            item.summary ||
                            item.why_care) && (
                            <div className="mt-1 flex flex-wrap items-center gap-1">
                              {hasFullText && <RunBadge>Full text</RunBadge>}
                              {fetchFailed && (
                                <RunBadge>Full text failed</RunBadge>
                              )}
                              {item.summary && <RunBadge>Summary</RunBadge>}
                              {item.why_care && <RunBadge>Why care</RunBadge>}
                            </div>
                          )}

                          {item.summary && (
                            <p className="mt-1.5 line-clamp-3 border-l-2 border-accent bg-accent-bg px-2 py-1 text-[11px] leading-4 text-ink">
                              <span className="font-bold">Summary:</span>{" "}
                              <HashtagText text={item.summary} />
                            </p>
                          )}

                          {body && (
                            <p className="mt-1 text-[11px] leading-4 text-muted">
                              {excerpt(body, hasFullText ? 320 : 180)}
                            </p>
                          )}

                          {item.why_care && (
                            <p className="mt-1.5 line-clamp-2 text-[11px] leading-4 text-muted">
                              <span className="font-bold text-ink">
                                Why you’d care:
                              </span>{" "}
                              <HashtagText text={item.why_care} />
                            </p>
                          )}

                          <div className="mt-1.5 flex items-center gap-2">
                            <Button
                              type="button"
                              variant="ghost"
                              size="xs"
                              className="-ml-1.5 gap-1 px-1.5"
                              onClick={() => setPreviewIndex(index)}
                            >
                              <BookOpen className="size-3" />
                              Read
                            </Button>
                            {item.link && (
                              <a
                                href={item.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[11px] text-accent hover:underline"
                              >
                                Original
                              </a>
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>

                  <div className="mt-3 space-y-2">
                    <p className="text-[11px] text-faint">
                      Showing {Math.min(visible, items.length)} of{" "}
                      {items.length} items.
                    </p>
                    {items.length > visible && (
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="w-full"
                        onClick={() =>
                          setVisible((current) => current + PAGE_SIZE)
                        }
                      >
                        Show {Math.min(PAGE_SIZE, items.length - visible)} more
                      </Button>
                    )}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </aside>

      <RunItemPreview
        items={items}
        index={previewIndex}
        onIndexChange={setPreviewIndex}
        onItemChange={(item) =>
          setOverrides((current) => ({ ...current, [item.id]: item }))
        }
      />
    </>
  );
}

function RunBadge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-sm border border-line bg-chrome px-1 py-0.5 text-[9px] font-bold uppercase tracking-[0.04em] text-muted">
      {children}
    </span>
  );
}
