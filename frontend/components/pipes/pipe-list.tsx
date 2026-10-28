"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Loader2,
  Plus,
  TriangleAlert,
  Workflow,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { boxDefinition } from "@/lib/pipes";
import { formatRelative } from "@/lib/text";

function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

export default function PipeList() {
  const pipesQuery = useQuery({
    queryKey: ["pipes"],
    queryFn: ({ signal }) => api.listPipes(signal),
  });

  const pipes = pipesQuery.data ?? [];

  return (
    <main className="mx-auto flex h-full w-full max-w-3xl flex-col overflow-y-auto px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-divider pb-4">
        <div>
          <h1 className="text-[20px] font-bold leading-tight">Pipes</h1>
          <p className="mt-1 max-w-[52ch] text-[13px] leading-5 text-muted">
            Chain boxes to gather, shape and understand a stream. Save a pipe,
            then run it against your feeds whenever you need it.
          </p>
        </div>
        <Button
          render={<Link href="/pipes/new" />}
          variant="primary"
          size="sm"
        >
          <Plus className="size-3.5" />
          New pipe
        </Button>
      </div>

      {pipesQuery.error && (
        <p
          role="alert"
          className="mt-4 flex items-start gap-2 border border-divider bg-chrome px-3 py-2 text-[12px] leading-5 text-danger"
        >
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          {messageOf(pipesQuery.error)}
        </p>
      )}

      {pipesQuery.isLoading ? (
        <p className="mt-8 flex items-center gap-2 text-[13px] text-muted">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Loading pipes…
        </p>
      ) : pipes.length === 0 ? (
        <div className="mt-10 border border-dashed border-line bg-sidebar px-6 py-10 text-center">
          <Workflow
            className="mx-auto size-8 text-faint"
            aria-hidden="true"
          />
          <h2 className="mt-3 text-[15px] font-bold">No pipes yet</h2>
          <p className="mx-auto mt-1 max-w-[42ch] text-[13px] leading-5 text-muted">
            Start with a Fetch box, add a few feeds, then shape the stream with
            Filter, Sort and Limit. AI boxes can summarize what comes through.
          </p>
          <Button
            render={<Link href="/pipes/new" />}
            variant="secondary"
            size="sm"
            className="mt-4"
          >
            Build your first pipe
          </Button>
        </div>
      ) : (
        <ul className="mt-2 divide-y divide-divider border-b border-divider">
          {pipes.map((pipe) => {
            const steps = pipe.spec_json.steps ?? [];
            return (
              <li key={pipe.id}>
                <Link
                  href={`/pipes/${pipe.id}`}
                  className="group flex items-center gap-3 py-3 text-ink hover:no-underline"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-sm border border-line bg-chrome">
                    <Workflow
                      className="size-4 text-muted"
                      aria-hidden="true"
                    />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-bold group-hover:text-accent">
                      {pipe.name}
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-muted">
                      {steps.length === 0
                        ? "Empty pipe"
                        : steps
                            .map((step) => boxDefinition(step.box).label)
                            .join(" → ")}
                    </span>
                  </span>
                  <span className="shrink-0 text-[11px] text-faint">
                    {steps.length} box{steps.length === 1 ? "" : "es"} ·{" "}
                    {formatRelative(pipe.updated_at)}
                  </span>
                  <ArrowRight
                    className="size-4 shrink-0 text-faint group-hover:text-accent"
                    aria-hidden="true"
                  />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
