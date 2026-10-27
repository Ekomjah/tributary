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

interface AddFeedDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (url: string) => Promise<string | null>;
}

export default function AddFeedDialog({
  open,
  onOpenChange,
  onSubmit,
}: AddFeedDialogProps) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = url.trim();
    if (!value || busy) {
      setError("Enter a feed URL first.");
      return;
    }

    setBusy(true);
    setError(null);
    const message = await onSubmit(value);
    setBusy(false);

    if (message) {
      setError(message);
      return;
    }

    setUrl("");
    onOpenChange(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setBusy(false);
          setError(null);
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
              Paste an RSS or Atom URL. Tributary fetches it once now, then
              keeps it in your local database.
            </DialogDescription>

            <label
              htmlFor="new-feed-url"
              className="mt-4 block text-[11px] font-bold uppercase tracking-[0.06em] text-muted"
            >
              Feed URL
            </label>
            <Input
              id="new-feed-url"
              type="url"
              inputMode="url"
              className="mt-1.5"
              placeholder="https://example.com/feed.xml"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                if (error) setError(null);
              }}
              autoComplete="off"
              spellCheck={false}
              autoFocus
            />

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
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Plus aria-hidden="true" />
              )}
              {busy ? "Adding…" : "Add feed"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
