"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy, Link2, Loader2, TriangleAlert } from "lucide-react";

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
import { api } from "@/lib/api";
import type { Item, ShareLink } from "@/lib/types";

interface ShareDialogProps {
  item: Item | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function messageOf(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

function ShareLinkBody({
  item,
  onClose,
}: {
  item: Item;
  onClose: () => void;
}) {
  const [link, setLink] = useState<ShareLink | null>(null);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const copyTimer = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    api
      .createShareLink(item.id)
      .then((created) => {
        if (cancelled) {
          return;
        }
        setLink(created);
        setUrl(`${window.location.origin}/shared/${created.token}`);
      })
      .catch((failure: unknown) => {
        if (!cancelled) {
          setError(messageOf(failure));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [item.id]);

  useEffect(() => {
    return () => {
      if (copyTimer.current !== null) {
        window.clearTimeout(copyTimer.current);
      }
    };
  }, []);

  async function copyLink() {
    if (!url) {
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      inputRef.current?.select();
      document.execCommand("copy");
    }
    setCopied(true);
    if (copyTimer.current !== null) {
      window.clearTimeout(copyTimer.current);
    }
    copyTimer.current = window.setTimeout(() => setCopied(false), 2200);
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Share this article</DialogTitle>
      </DialogHeader>
      <div className="space-y-3 px-4 py-4">
        <DialogDescription>
          Anyone signed in to this Tributary deployment can use this private
          link once. They get their own copy in{" "}
          <span className="font-bold text-ink">Shared with me</span>; your read,
          star and label state stays yours.
        </DialogDescription>

        <p className="truncate border-l-[3px] border-l-accent bg-chrome px-2 py-1.5 text-[12px] text-muted">
          {item.title || "Untitled"}
        </p>

        {error ? (
          <div
            role="alert"
            className="flex items-start gap-1.5 border border-line bg-chrome px-2.5 py-2 text-[12px] leading-5 text-danger"
          >
            <TriangleAlert
              className="mt-0.5 size-3.5 shrink-0"
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1">
              Could not create a share link. {error}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Link2
                className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-faint"
                aria-hidden="true"
              />
              <Input
                ref={inputRef}
                readOnly
                value={url}
                placeholder="Creating a private link…"
                aria-label="Private share link"
                className="pl-7 font-mono text-[11px]"
                onFocus={(event) => event.currentTarget.select()}
              />
            </div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="h-8 shrink-0"
              disabled={!url}
              onClick={() => void copyLink()}
            >
              {!link ? (
                <Loader2
                  className="size-3.5 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              ) : copied ? (
                <Check className="size-3.5 text-success" aria-hidden="true" />
              ) : (
                <Copy className="size-3.5" aria-hidden="true" />
              )}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        )}

        {link && (
          <p className="text-[11px] leading-4 text-faint">
            This link is single-use and expires on{" "}
            {new Date(link.expires_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
            . Create another one from the article if you want to share it with
            someone else.
          </p>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="secondary" size="sm" onClick={onClose}>
          Done
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export default function ShareDialog({
  item,
  open,
  onOpenChange,
}: ShareDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && item !== null && (
        <ShareLinkBody item={item} onClose={() => onOpenChange(false)} />
      )}
    </Dialog>
  );
}
