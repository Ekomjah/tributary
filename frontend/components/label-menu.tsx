"use client";

import { useState } from "react";
import { Check, Tag } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { Label } from "@/lib/types";
import { cn } from "@/lib/utils";

interface LabelMenuProps {
  labels: Label[];
  selected: Label[];
  onToggle: (label: Label) => void;
  triggerClassName?: string;
}

export default function LabelMenu({
  labels,
  selected,
  onToggle,
  triggerClassName,
}: LabelMenuProps) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="icon"
            size="icon-sm"
            className={cn("text-faint hover:text-ink", triggerClassName)}
            aria-label="Add label"
            title="Add label"
          />
        }
        onClick={(event) => event.stopPropagation()}
      >
        <Tag className="size-3.5" />
      </PopoverTrigger>
      <PopoverContent className="w-52">
        <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-faint">
          Labels
        </p>
        {labels.length === 0 ? (
          <p className="px-2 py-1.5 text-[12px] text-muted">
            No labels yet. Create one in the sidebar.
          </p>
        ) : (
          labels.map((entry) => {
            const attached = selected.some(
              (itemLabel) => itemLabel.id === entry.id,
            );
            return (
              <button
                key={entry.id}
                type="button"
                onClick={() => {
                  onToggle(entry);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12px] text-ink hover:bg-accent-bg"
              >
                <span
                  className={cn(
                    "grid size-3.5 shrink-0 place-items-center border",
                    attached
                      ? "border-accent bg-accent text-white"
                      : "border-line bg-canvas",
                  )}
                >
                  {attached && <Check className="size-2.5" />}
                </span>
                <span className="truncate">{entry.name}</span>
              </button>
            );
          })
        )}
      </PopoverContent>
    </Popover>
  );
}
