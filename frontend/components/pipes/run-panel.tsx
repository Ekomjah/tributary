"use client";

import {
  CircleCheck,
  Clock,
  ExternalLink,
  Loader2,
  TriangleAlert,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PipeRun } from "@/lib/types";
import { excerpt, formatRelative, hostOf } from "@/lib/text";
import { cn } from "@/lib/utils";

interface RunPanelProps {
  result: PipeRun | null;
  error: string | null;
  running: boolean;
  onClose: () => void;
}

const PREVIEW_LIMIT = 50;

export default function RunPanel({
  result,
  error,
  running,
  onClose,
}: RunPanelProps) {
  if (!running && !result && !error) {
    return null;
  }

  return (
    <aside
      className="flex w-[340px] shrink-0 flex-col border-l border-divider bg-canvas max-[900px]:w-full max-[900px]:border-l-0 max-[900px]:border-t"
      aria-live="polite"
    >
      <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-divider bg-chrome px-3">
        <div className="flex min-w-0 items-center gap-1.5">
          {running ? (
            <Loader2 className="size-3.5 animate-spin text-accent" />
          ) : error ? (
            <TriangleAlert className="size-3.5 text-danger" />
          ) : (
            <CircleCheck className="size-3.5 text-success" />
          )}
          <h2 className="truncate text-[12px] font-bold">
            {running ? "Running…" : error ? "Run failed" : "Results"}
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
          <p className="flex items-start gap-2 text-[12px] leading-5 text-danger">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
            {error}
          </p>
        )}

        {result && !running && (
          <>
            <p className="text-[12px] text-muted">
              <strong className="text-ink">{result.items.length}</strong> item
              {result.items.length === 1 ? "" : "s"} in{" "}
              <strong className="text-ink">
                {(result.run.seconds ?? 0).toFixed(2)}s
              </strong>
            </p>

            <div className="mt-3 border-y border-divider">
              {result.steps.map((step, index) => {
                const slow = step.seconds > 2;
                return (
                  <div
                    key={`${step.box}-${index}`}
                    className="flex items-center gap-2 border-b border-divider py-1.5 text-[11px] last:border-b-0"
                  >
                    <span className="w-4 shrink-0 font-mono text-faint">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-bold">
                      {step.box}
                    </span>
                    <span className="shrink-0 font-mono text-faint">
                      {step.items_in} → {step.items_out}
                    </span>
                    <span
                      className={cn(
                        "flex w-14 shrink-0 items-center justify-end gap-1 font-mono",
                        slow ? "text-warn" : "text-muted",
                      )}
                    >
                      {slow && <Clock className="size-3" />}
                      {step.seconds.toFixed(2)}s
                    </span>
                  </div>
                );
              })}
            </div>

            {result.items.length === 0 ? (
              <p className="mt-4 text-[12px] leading-5 text-muted">
                No items. Check the source boxes and filters.
              </p>
            ) : (
              <div className="mt-3 space-y-3">
                {result.items.slice(0, PREVIEW_LIMIT).map((item, index) => {
                  const key = item.guid || item.link || `${item.title}-${index}`;
                  const source =
                    item.source || (item.link ? hostOf(item.link) : "Search result");
                  return (
                    <article
                      key={key}
                      className="border-b border-divider pb-3 last:border-b-0"
                    >
                      <div className="flex items-start gap-1.5">
                        {item.link ? (
                          <a
                            href={item.link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="min-w-0 flex-1 text-[13px] font-bold leading-5 text-accent hover:underline"
                          >
                            {item.title || item.link}
                          </a>
                        ) : (
                          <span className="min-w-0 flex-1 text-[13px] font-bold leading-5">
                            {item.title}
                          </span>
                        )}
                        {item.link && (
                          <ExternalLink className="mt-1 size-3 shrink-0 text-faint" />
                        )}
                      </div>
                      <p className="mt-0.5 text-[10px] text-faint">
                        {source} · {formatRelative(item.published)}
                      </p>
                      {item.content && (
                        <p className="mt-1 text-[11px] leading-4 text-muted">
                          {excerpt(item.content, 180)}
                        </p>
                      )}
                    </article>
                  );
                })}
                {result.items.length > PREVIEW_LIMIT && (
                  <p className="text-[11px] text-faint">
                    Showing the first {PREVIEW_LIMIT} of {result.items.length}{" "}
                    items.
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
