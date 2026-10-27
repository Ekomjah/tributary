"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Loader2, Tag, TriangleAlert } from "lucide-react";

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

interface AddLabelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (name: string) => Promise<string | null>;
}

export default function AddLabelDialog({
  open,
  onOpenChange,
  onSubmit,
}: AddLabelDialogProps) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = name.trim();
    if (!value || busy) {
      setError("Enter a label name first.");
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

    setName("");
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
      <DialogContent className="sm:max-w-[400px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New label</DialogTitle>
          </DialogHeader>

          <div className="px-4 py-4">
            <DialogDescription>
              Labels are local, shared across feeds, and applied to one item at
              a time.
            </DialogDescription>

            <label
              htmlFor="new-label-name"
              className="mt-4 block text-[11px] font-bold uppercase tracking-[0.06em] text-muted"
            >
              Label name
            </label>
            <Input
              id="new-label-name"
              type="text"
              className="mt-1.5"
              placeholder="Long reads"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                if (error) setError(null);
              }}
              maxLength={100}
              autoComplete="off"
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
                <Tag aria-hidden="true" />
              )}
              {busy ? "Creating…" : "Create label"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
