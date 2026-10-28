"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Loader2, Plus, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { FeedCandidate, FeedDiscovery } from "@/lib/types";

interface AddFeedDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDiscover: (url: string) => Promise<FeedDiscovery>;
  onAdd: (url: string) => Promise<string | null>;
}

type Stage = "idle" | "finding" | "choose" | "adding";

function messageOf(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

function hostOf(value: string): string {
  try {
    return new URL(value).hostname;
  } catch {
    return value;
  }
}

export default function AddFeedDialog({
  open,
  onOpenChange,
  onDiscover,
  onAdd,
}: AddFeedDialogProps) {
  const [url, setUrl] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [candidates, setCandidates] = useState<FeedCandidate[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [pageTitle, setPageTitle] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const busy = stage === "finding" || stage === "adding";

  function reset() {
    setUrl("");
    setStage("idle");
    setCandidates([]);
    setSelected(null);
    setPageTitle(null);
    setError(null);
  }

  async function findFeeds(value: string) {
    setStage("finding");
    setError(null);
    setCandidates([]);
    setSelected(null);
    setPageTitle(null);

    try {
      const result = await onDiscover(value);
      if (result.candidates.length === 0) {
        setStage("idle");
        setError("No feed found at that address. Try the feed URL directly.");
        return;
      }

      setCandidates(result.candidates);
      setPageTitle(result.page_title);
      setSelected(result.candidates[0].url);
      setStage("choose");
    } catch (caught) {
      setStage("idle");
      setError(messageOf(caught));
    }
  }

  async function addSelected(candidateUrl: string) {
    setStage("adding");
    setError(null);

    const message = await onAdd(candidateUrl);
    if (message) {
      setError(message);
      setStage("choose");
      return;
    }

    reset();
    onOpenChange(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) {
      return;
    }

    if (stage === "choose" && selected) {
      await addSelected(selected);
      return;
    }

    const value = url.trim();
    if (!value) {
      setError("Enter a blog or feed URL first.");
      return;
    }

    await findFeeds(value);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset();
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-[440px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Add feed</DialogTitle>
          </DialogHeader>

          <div className="px-4 py-4">
            <DialogDescription>
              Paste a blog or feed URL. Tributary finds the feed, fetches it
              once, then keeps it in your local database.
            </DialogDescription>

            <label
              htmlFor="new-feed-url"
              className="mt-4 block text-[11px] font-bold uppercase tracking-[0.06em] text-muted"
            >
              Blog or feed URL
            </label>
            <Input
              id="new-feed-url"
              type="text"
              inputMode="url"
              className="mt-1.5"
              placeholder="example.com"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                if (error) {
                  setError(null);
                }
                if (stage === "choose") {
                  setStage("idle");
                  setCandidates([]);
                  setSelected(null);
                  setPageTitle(null);
                }
              }}
              autoComplete="off"
              spellCheck={false}
              autoFocus
              disabled={busy}
            />

            {stage === "finding" && (
              <p
                role="status"
                className="mt-3 flex items-center gap-2 text-[12px] text-muted"
              >
                <Loader2
                  className="size-3.5 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
                Looking for a feed…
              </p>
            )}

            {stage === "choose" && candidates.length > 0 && (
              <fieldset className="mt-3">
                <legend className="text-[11px] font-bold uppercase tracking-[0.06em] text-muted">
                  {candidates.length === 1
                    ? "Feed found"
                    : `Found ${candidates.length} feeds`}
                </legend>
                {pageTitle && (
                  <p className="mt-1 text-[11px] text-faint">on {pageTitle}</p>
                )}
                <div className="mt-2 space-y-1.5">
                  {candidates.map((candidate) => (
                    <label
                      key={candidate.url}
                      className="flex cursor-pointer items-start gap-2 border border-line bg-white px-2.5 py-2 text-[12px] leading-4 hover:bg-[#f7f7f7]"
                    >
                      <input
                        type="radio"
                        name="feed-candidate"
                        value={candidate.url}
                        checked={selected === candidate.url}
                        onChange={() => setSelected(candidate.url)}
                        className="mt-0.5 accent-[var(--red)]"
                      />
                      <span className="min-w-0">
                        <span className="block truncate font-bold text-ink">
                          {candidate.title || hostOf(candidate.url)}
                        </span>
                        <span className="mt-0.5 block break-all font-mono text-[10px] leading-4 text-faint">
                          {candidate.url}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

            {error && (
              <p
                role="alert"
                className="mt-2 flex items-start gap-1.5 text-[12px] leading-5 text-danger"
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
              onClick={() => {
                reset();
                onOpenChange(false);
              }}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={busy || (stage === "choose" && !selected)}
            >
              {busy ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Plus aria-hidden="true" />
              )}
              {stage === "finding"
                ? "Finding…"
                : stage === "adding"
                  ? "Adding…"
                  : stage === "choose"
                    ? "Add feed"
                    : "Find feed"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
