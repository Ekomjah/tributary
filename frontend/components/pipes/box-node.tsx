"use client";

import { useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  ArrowUpDown,
  Brain,
  CircleCheck,
  Clock,
  Copy,
  FileText,
  Filter,
  GitMerge,
  Lightbulb,
  ListOrdered,
  Loader2,
  Rss,
  Search,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { api } from "@/lib/api";
import {
  boxDefinition,
  freshnessOptions,
  type BoxNode,
  type BoxType,
  type NodeRunState,
} from "@/lib/pipes";
import type {
  DedupeStep,
  PipeStep,
  SearchStep,
  SortStep,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { usePipeGraph } from "./pipe-context";

const ICONS: Record<BoxType, typeof Rss> = {
  fetch: Rss,
  search: Search,
  merge: GitMerge,
  dedupe: Copy,
  filter: Filter,
  sort: ArrowUpDown,
  limit: ListOrdered,
  fulltext: FileText,
  summarize: Sparkles,
  meaning: Brain,
  whycare: Lightbulb,
};

const inputClass =
  "nodrag nowheel h-7 w-full rounded-sm border border-line bg-canvas px-1.5 text-[12px] outline-none focus:border-accent";
const labelClass =
  "block text-[10px] font-bold uppercase tracking-[0.06em] text-muted";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className={labelClass}>{label}</span>
      {children}
    </label>
  );
}

function RunBadge({ run }: { run?: NodeRunState }) {
  if (!run) {
    return null;
  }

  if (run.status === "running") {
    return (
      <Loader2
        className="size-3.5 animate-spin text-accent"
        aria-label="Running"
      />
    );
  }
  if (run.status === "error") {
    return (
      <TriangleAlert className="size-3.5 text-danger" aria-label="Failed" />
    );
  }
  if (run.status === "slow") {
    return (
      <span className="flex items-center gap-1 text-[10px] text-warn">
        <Clock className="size-3.5" aria-hidden="true" />
        {run.seconds !== undefined ? `${run.seconds.toFixed(1)}s` : "slow"}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[10px] text-success">
      <CircleCheck className="size-3.5" aria-hidden="true" />
      {run.itemsOut ?? 0}
    </span>
  );
}

export default function BoxNodeView({ id, data, selected }: NodeProps<BoxNode>) {
  const { updateStep } = usePipeGraph();
  const step = data.step;
  const definition = boxDefinition(step.box);
  const Icon = ICONS[step.box];
  const usesModel =
    step.box === "summarize" ||
    step.box === "meaning" ||
    step.box === "whycare" ||
    (step.box === "search" && step.refine !== false);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  function update(patch: Record<string, unknown>) {
    updateStep(id, { ...step, ...patch } as PipeStep);
  }

  async function previewQuery() {
    if (step.box !== "search" || !step.query.trim()) {
      return;
    }
    setPreviewing(true);
    setPreview(null);
    setPreviewError(null);
    try {
      const refined = await api.refineSearch(step.query.trim());
      const freshness = refined.spec.freshness
        ? ` · ${refined.spec.freshness}`
        : "";
      setPreview(
        `“${refined.spec.q}” · ${refined.spec.engine}${freshness} · ${refined.spec.max_results} results`,
      );
      if (refined.fallback) {
        setPreviewError("Local model unavailable; using your request as-is.");
      }
    } catch (error) {
      setPreviewError(
        error instanceof Error ? error.message : "Could not refine the query.",
      );
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <div
      className={cn(
        "w-[200px] rounded-sm border bg-canvas text-ink",
        selected
          ? "border-accent ring-1 ring-accent ring-offset-1"
          : "border-line",
      )}
    >
      {usesModel && <div className="h-[3px] bg-accent" />}

      <div className="flex h-7 items-center gap-1.5 border-b border-divider bg-chrome px-2">
        <Icon className="size-3.5 shrink-0 text-muted" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-[12px] font-bold">
          {definition.label}
        </span>
        {usesModel && (
          <span className="rounded-sm border border-accent px-1 text-[9px] font-bold text-accent">
            AI
          </span>
        )}
        <RunBadge run={data.run} />
      </div>

      <div className="space-y-2 p-2">
        {step.box === "fetch" && (
          <Field label="Feed URLs">
            <textarea
              className={cn(inputClass, "min-h-14 resize-y py-1 leading-4")}
              value={step.urls.join("\n")}
              placeholder="https://hnrss.org/frontpage"
              spellCheck={false}
              onChange={(event) =>
                update({ urls: event.target.value.split("\n") })
              }
              onBlur={() =>
                update({
                  urls: step.urls.map((url) => url.trim()).filter(Boolean),
                })
              }
            />
          </Field>
        )}

        {step.box === "search" && (
          <>
            <Field label="Request">
              <textarea
                className={cn(inputClass, "min-h-14 resize-y py-1 leading-4")}
                value={step.query}
                placeholder="AI regulation this week"
                onChange={(event) => update({ query: event.target.value })}
              />
            </Field>
            <div className="grid grid-cols-2 gap-1.5">
              <Field label="Engine">
                <select
                  className={inputClass}
                  value={step.engine ?? "google_news"}
                  onChange={(event) =>
                    update({
                      engine: event.target.value as SearchStep["engine"],
                    })
                  }
                >
                  <option value="google_news">Google News</option>
                  <option value="google">Google</option>
                </select>
              </Field>
              <Field label="Freshness">
                <select
                  className={inputClass}
                  value={step.freshness ?? ""}
                  onChange={(event) =>
                    update({
                      freshness: (event.target.value ||
                        null) as SearchStep["freshness"],
                    })
                  }
                >
                  <option value="">Any time</option>
                  {freshnessOptions().map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Max results">
              <input
                type="number"
                min={1}
                max={20}
                className={inputClass}
                value={step.max_results ?? 10}
                onChange={(event) =>
                  update({ max_results: Number(event.target.value) })
                }
              />
            </Field>
            <label className="nodrag flex items-center gap-1.5 text-[11px] text-muted">
              <input
                type="checkbox"
                checked={step.refine !== false}
                onChange={(event) => update({ refine: event.target.checked })}
              />
              Refine with the local model
            </label>
            {step.refine !== false && (
              <>
                <button
                  type="button"
                  className="nodrag inline-flex items-center gap-1 text-[11px] font-bold text-accent hover:text-accent-dark disabled:text-faint"
                  onClick={() => void previewQuery()}
                  disabled={previewing || !step.query.trim()}
                >
                  {previewing ? (
                    <Loader2
                      className="size-3 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <Sparkles className="size-3" aria-hidden="true" />
                  )}
                  Preview query
                </button>
                {preview && (
                  <p className="rounded-sm border border-divider bg-chrome px-1.5 py-1 text-[10px] leading-4 text-muted">
                    {preview}
                  </p>
                )}
                {previewError && (
                  <p className="text-[10px] leading-4 text-warn">
                    {previewError}
                  </p>
                )}
              </>
            )}
          </>
        )}

        {step.box === "merge" && (
          <p className="text-[11px] leading-4 text-muted">
            Joins the source boxes earlier in the chain.
          </p>
        )}

        {step.box === "dedupe" && (
          <Field label="Keep unique by">
            <select
              className={inputClass}
              value={step.by ?? "link"}
              onChange={(event) =>
                update({ by: event.target.value as DedupeStep["by"] })
              }
            >
              <option value="link">Link</option>
              <option value="guid">GUID</option>
              <option value="title">Title</option>
            </select>
          </Field>
        )}

        {step.box === "filter" && (
          <>
            <Field label="Keyword">
              <input
                className={inputClass}
                value={step.keyword}
                placeholder="python"
                onChange={(event) => update({ keyword: event.target.value })}
              />
            </Field>
            <fieldset className="nodrag space-y-1">
              <legend className={labelClass}>Fields</legend>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {(["title", "content", "link"] as const).map((field) => (
                  <label
                    key={field}
                    className="flex items-center gap-1 text-[11px] text-muted"
                  >
                    <input
                      type="checkbox"
                      checked={(step.fields ?? ["title", "content"]).includes(
                        field,
                      )}
                      onChange={(event) => {
                        const current = step.fields ?? ["title", "content"];
                        const next = event.target.checked
                          ? [...current, field]
                          : current.filter((entry) => entry !== field);
                        update({ fields: next });
                      }}
                    />
                    {field}
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        )}

        {step.box === "sort" && (
          <div className="grid grid-cols-2 gap-1.5">
            <Field label="Sort by">
              <select
                className={inputClass}
                value={step.by ?? "published"}
                onChange={(event) =>
                  update({ by: event.target.value as SortStep["by"] })
                }
              >
                <option value="published">Published</option>
                <option value="fetched_at">Fetched</option>
                <option value="title">Title</option>
              </select>
            </Field>
            <Field label="Order">
              <select
                className={inputClass}
                value={step.order ?? "desc"}
                onChange={(event) =>
                  update({ order: event.target.value as SortStep["order"] })
                }
              >
                <option value="desc">Descending</option>
                <option value="asc">Ascending</option>
              </select>
            </Field>
          </div>
        )}

        {step.box === "limit" && (
          <Field label="Keep first">
            <input
              type="number"
              min={1}
              max={500}
              className={inputClass}
              value={step.count ?? 10}
              onChange={(event) => update({ count: Number(event.target.value) })}
            />
          </Field>
        )}

        {step.box === "fulltext" && (
          <p className="text-[11px] leading-4 text-muted">
            Fetches each article and stores the full text on the item.
          </p>
        )}

        {step.box === "summarize" && (
          <p className="text-[11px] leading-4 text-muted">
            Writes a one-line summary for every item that has full text.
          </p>
        )}

        {step.box === "meaning" && (
          <Field label="Keep items about">
            <textarea
              className={cn(inputClass, "min-h-14 resize-y py-1 leading-4")}
              value={step.criterion}
              placeholder="databases, not hype"
              onChange={(event) =>
                update({ criterion: event.target.value })
              }
            />
          </Field>
        )}

        {step.box === "whycare" && (
          <p className="text-[11px] leading-4 text-muted">
            Adds one sentence about why an item might matter, learned from
            your stars.
          </p>
        )}
      </div>

      <Handle
        type="target"
        position={Position.Left}
        className="!size-2 !rounded-none !border !border-faint !bg-canvas"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!size-2 !rounded-none !border !border-faint !bg-canvas"
      />
    </div>
  );
}
