"use client";

import { useState } from "react";
import { Loader2, Trash2, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Feed } from "@/lib/types";

interface DeleteFeedDialogProps {
  feed: Feed | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<string | null>;
}

export default function DeleteFeedDialog({
  feed,
  onOpenChange,
  onConfirm,
}: DeleteFeedDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    setBusy(false);
    setError(null);
    onOpenChange(false);
  }

  async function handleDelete() {
    if (!feed || busy) {
      return;
    }

    setBusy(true);
    setError(null);
    const message = await onConfirm();
    if (message) {
      setError(message);
      setBusy(false);
      return;
    }

    close();
  }

  const name = feed ? feed.title || feed.url : "";
  const isSearch = feed?.kind === "search";

  return (
    <Dialog
      open={feed !== null}
      onOpenChange={(next) => {
        if (!next) {
          if (busy) {
            return;
          }
          setBusy(false);
          setError(null);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>{isSearch ? "Delete search?" : "Delete feed?"}</DialogTitle>
        </DialogHeader>

        <div className="px-4 py-4">
          <DialogDescription>
            {isSearch ? (
              <>“{name}” will be removed from Tributary. This can’t be undone.</>
            ) : (
              <>
                “{name}” and all articles saved from it will be removed from
                Tributary. This can’t be undone.
              </>
            )}
          </DialogDescription>

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
            onClick={close}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={handleDelete}
            disabled={busy || !feed}
          >
            {busy ? (
              <Loader2 className="animate-spin" aria-hidden="true" />
            ) : (
              <Trash2 aria-hidden="true" />
            )}
            {busy ? "Deleting…" : isSearch ? "Delete search" : "Delete feed"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
