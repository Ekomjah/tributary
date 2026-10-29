"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CircleCheck,
  Loader2,
  TriangleAlert,
} from "lucide-react";

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
import { formatRelative } from "@/lib/text";
import type { PipeRun, PipeRunRecord } from "@/lib/types";

interface RunHistoryProps {
  pipeId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenRun: (run: PipeRun) => void;
}

function messageOf(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Could not load run history.";
}

function StatusIcon({ status }: { status: PipeRunRecord["status"] }) {
  if (status === "error") {
    return (
      <TriangleAlert
        className="mt-0.5 size-3.5 shrink-0 text-danger"
        aria-hidden="true"
      />
    );
  }
  if (status === "running") {
    return (
      <Loader2
        className="mt-0.5 size-3.5 shrink-0 animate-spin text-accent"
        aria-hidden="true"
      />
    );
  }
  return (
    <CircleCheck
      className="mt-0.5 size-3.5 shrink-0 text-success"
      aria-hidden="true"
    />
  );
}

export default function RunHistory({
  pipeId,
  open,
  onOpenChange,
  onOpenRun,
}: RunHistoryProps) {
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runsQuery = useQuery({
    queryKey: ["pipe-runs", pipeId],
    queryFn: ({ signal }) => api.listPipeRuns(pipeId as number, 20, signal),
    enabled: open && pipeId !== null,
  });

  function handleOpenChange(next: boolean) {
    if (!next) {
      setOpeningId(null);
      setError(null);
    }
    onOpenChange(next);
  }

  async function openRun(run: PipeRunRecord) {
    if (openingId !== null) {
      return;
    }
    setOpeningId(run.id);
    setError(null);
    try {
      const result = await api.getPipeRun(run.id);
      onOpenRun(result);
      onOpenChange(false);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setOpeningId((current) => (current === run.id ? null : current));
    }
  }

  const runs = runsQuery.data ?? [];
  const queryError = runsQuery.error
    ? messageOf(runsQuery.error)
    : null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>Run history</DialogTitle>
          <DialogDescription>
            Reopen a previous run. Items are rebuilt from their saved ids, so
            read, star and decision state stays current.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] min-h-[140px] overflow-y-auto px-4 py-3">
          {runsQuery.isLoading ? (
            <p className="flex items-center gap-2 py-6 text-[12px] text-muted">
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
              Loading runs…
            </p>
          ) : queryError ? (
            <p
              role="alert"
              className="flex items-start gap-2 py-3 text-[12px] leading-5 text-danger"
            >
              <TriangleAlert
                className="mt-0.5 size-3.5 shrink-0"
                aria-hidden="true"
              />
              {queryError}
            </p>
          ) : runs.length === 0 ? (
            <p className="py-6 text-[12px] leading-5 text-muted">
              No runs yet. Run this pipe to start its history.
            </p>
          ) : (
            <ul>
              {runs.map((run) => (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => void openRun(run)}
                    disabled={openingId !== null}
                    className="flex w-full items-start gap-2 border-b border-divider px-1 py-2 text-left last:border-b-0 hover:bg-[#f0f0f0] disabled:opacity-60"
                  >
                    <StatusIcon status={run.status} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <span className="text-[12px] font-bold">
                          Run #{run.id}
                        </span>
                        <span className="text-[11px] text-faint">
                          {formatRelative(run.started)}
                        </span>
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted">
                        <span>
                          {run.result_count} item
                          {run.result_count === 1 ? "" : "s"}
                        </span>
                        {run.seconds !== null && (
                          <span className="font-mono">
                            {run.seconds.toFixed(2)}s
                          </span>
                        )}
                        {run.status !== "success" && (
                          <span
                            className={
                              run.status === "error"
                                ? "text-danger"
                                : "text-warn"
                            }
                          >
                            {run.status === "error"
                              ? run.error_box
                                ? `failed at ${run.error_box}`
                                : "failed"
                              : "running"}
                          </span>
                        )}
                      </span>
                      {run.error && (
                        <span className="mt-0.5 line-clamp-2 block text-[11px] leading-4 text-danger">
                          {run.error}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 pt-0.5 text-[11px] text-accent">
                      {openingId === run.id ? (
                        <Loader2
                          className="size-3.5 animate-spin"
                          aria-hidden="true"
                        />
                      ) : (
                        "Open"
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {error && (
            <p
              role="alert"
              className="mt-2 flex items-start gap-2 border-t border-divider pt-2 text-[12px] leading-5 text-danger"
            >
              <TriangleAlert
                className="mt-0.5 size-3.5 shrink-0"
                aria-hidden="true"
              />
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="secondary"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
