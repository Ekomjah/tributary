"use client";

import {
  ArrowUpDown,
  Brain,
  Copy,
  FileText,
  Filter,
  GitMerge,
  Lightbulb,
  ListOrdered,
  Rss,
  Search,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import {
  BOX_DEFINITIONS,
  type BoxGroup,
  type BoxType,
} from "@/lib/pipes";
import { cn } from "@/lib/utils";

const ICONS: Record<BoxType, LucideIcon> = {
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

const GROUP_ORDER: BoxGroup[] = [
  "Sources",
  "Combine",
  "Transform",
  "Understand",
  "Output",
];

interface BoxPaletteProps {
  onAdd: (type: BoxType) => void;
}

export default function BoxPalette({ onAdd }: BoxPaletteProps) {
  return (
    <aside className="flex w-[176px] shrink-0 flex-col overflow-y-auto border-r border-divider bg-sidebar">
      <div className="border-b border-divider px-3 py-2">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.06em] text-muted">
          Boxes
        </h2>
        <p className="mt-0.5 text-[10px] leading-4 text-faint">
          Drag onto the canvas, or click to add.
        </p>
      </div>

      <div className="flex flex-col gap-3 p-2">
        {GROUP_ORDER.map((group) => {
          const entries = BOX_DEFINITIONS.filter(
            (definition) => definition.group === group,
          );
          if (entries.length === 0) {
            return null;
          }

          return (
            <section key={group}>
              <h3 className="mb-1 px-1 text-[10px] font-bold uppercase tracking-[0.06em] text-faint">
                {group}
              </h3>
              <div className="flex flex-col gap-1">
                {entries.map((definition) => {
                  const Icon = ICONS[definition.type];
                  return (
                    <button
                      key={definition.type}
                      type="button"
                      draggable={definition.available}
                      disabled={!definition.available}
                      title={definition.description}
                      onClick={() => onAdd(definition.type)}
                      onDragStart={(event) => {
                        event.dataTransfer.setData(
                          "application/tributary-box",
                          definition.type,
                        );
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-sm border border-line bg-canvas px-2 py-1.5 text-left text-[12px] text-ink hover:bg-chrome disabled:border-divider disabled:bg-transparent disabled:text-faint",
                      )}
                    >
                      <Icon
                        className="size-3.5 shrink-0 text-muted"
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {definition.label}
                      </span>
                      {!definition.available && (
                        <span className="shrink-0 rounded-sm border border-divider px-1 text-[9px] uppercase text-faint">
                          Soon
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>

      <p className="mt-auto border-t border-divider p-3 text-[10px] leading-4 text-faint">
        MVP pipes run as one chain. Use Merge after your source boxes.
      </p>
    </aside>
  );
}
