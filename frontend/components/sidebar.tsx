import Link from "next/link";
import {
  Inbox,
  Info,
  Library,
  Lock,
  Plus,
  Rss,
  Search,
  Star,
  Tag,
  Workflow,
} from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { Feed, ItemView, Label } from "@/lib/types";
import { cn } from "@/lib/utils";

const VIEWS: {
  id: ItemView;
  label: string;
  icon: ComponentType<{ className?: string }>;
}[] = [
  { id: "all", label: "All items", icon: Library },
  { id: "unread", label: "Unread", icon: Inbox },
  { id: "starred", label: "Starred items", icon: Star },
];

interface SidebarProps {
  feeds: Feed[];
  feedCounts: Record<number, number>;
  labels: Label[];
  view: ItemView;
  feedId: number | null;
  label: string | null;
  viewCounts: Record<ItemView, number>;
  onSelectView: (view: ItemView) => void;
  onSelectFeed: (feedId: number | null) => void;
  onSelectLabel: (name: string) => void;
  onAddFeed: () => void;
  onAddLabel: () => void;
}

function Row({
  active,
  icon: Icon,
  children,
  count,
  onClick,
  title,
}: {
  active: boolean;
  icon: ComponentType<{ className?: string }>;
  children: ReactNode;
  count?: number;
  onClick: () => void;
  title?: string;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      title={title}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={cn(
        "h-7 w-full justify-start gap-2 rounded-none border-l-[3px] px-2 text-left text-[13px] font-normal",
        active
          ? "border-accent bg-accent-bg font-bold text-ink"
          : "border-transparent hover:bg-[#f0f0f0]",
      )}
    >
      <Icon
        className={cn(
          "size-4 shrink-0",
          active ? "text-accent" : "text-muted",
        )}
      />
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {typeof count === "number" && count > 0 && (
        <span className="shrink-0 font-mono text-[11px] font-normal text-faint">
          ({count})
        </span>
      )}
    </Button>
  );
}

function SectionTitle({
  children,
  action,
}: {
  children: ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-1 flex h-6 items-center justify-between px-2">
      <h2 className="text-[11px] font-bold uppercase tracking-[0.06em] text-muted">
        {children}
      </h2>
      {action}
    </div>
  );
}

export default function Sidebar({
  feeds,
  feedCounts,
  labels,
  view,
  feedId,
  label,
  viewCounts,
  onSelectView,
  onSelectFeed,
  onSelectLabel,
  onAddFeed,
  onAddLabel,
}: SidebarProps) {
  const subscriptions = feeds.filter((feed) => feed.kind !== "search");
  const searches = feeds.filter((feed) => feed.kind === "search");

  return (
    <div className="flex h-full flex-col bg-sidebar">
      <div className="flex-1 overflow-y-auto py-3">
        <nav aria-label="Views" className="flex flex-col">
          {VIEWS.map((entry) => (
            <Row
              key={entry.id}
              active={view === entry.id && feedId === null && label === null}
              icon={entry.icon}
              count={viewCounts[entry.id]}
              onClick={() => onSelectView(entry.id)}
            >
              {entry.label}
            </Row>
          ))}
        </nav>

        <div className="my-2 border-t border-divider" />

        <section aria-labelledby="sidebar-tools">
          <SectionTitle>
            <span id="sidebar-tools">Tools</span>
          </SectionTitle>
          <Link
            href="/pipes"
            className="flex h-7 w-full items-center gap-2 rounded-none border-l-[3px] border-transparent px-2 text-left text-[13px] text-ink hover:bg-[#f0f0f0] hover:no-underline"
          >
            <Workflow className="size-4 shrink-0 text-muted" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">Pipes</span>
          </Link>
          <Link
            href="/"
            className="flex h-7 w-full items-center gap-2 rounded-none border-l-[3px] border-transparent px-2 text-left text-[13px] text-ink hover:bg-[#f0f0f0] hover:no-underline"
          >
            <Info className="size-4 shrink-0 text-muted" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">About Tributary</span>
          </Link>
        </section>

        <div className="my-2 border-t border-divider" />

        <section aria-labelledby="sidebar-feeds">
          <SectionTitle
            action={
              <Button
                type="button"
                variant="icon"
                size="icon-xs"
                onClick={onAddFeed}
                aria-label="Add feed"
                title="Add feed"
              >
                <Plus className="size-3.5" />
              </Button>
            }
          >
            <span id="sidebar-feeds">Feeds</span>
          </SectionTitle>

          <div className="flex flex-col">
            {subscriptions.length === 0 ? (
              <p className="px-2 py-1 text-[12px] text-faint">No feeds yet.</p>
            ) : (
              subscriptions.map((feed) => (
                <Row
                  key={feed.id}
                  active={feedId === feed.id}
                  icon={Rss}
                  count={feedCounts[feed.id] ?? 0}
                  title={feed.url}
                  onClick={() => onSelectFeed(feed.id)}
                >
                  {feed.title || feed.url}
                </Row>
              ))
            )}
          </div>
        </section>

        <div className="my-2 border-t border-divider" />

        <section aria-labelledby="sidebar-searches">
          <SectionTitle>
            <span id="sidebar-searches">Searches</span>
          </SectionTitle>

          <div className="flex flex-col">
            {searches.length === 0 ? (
              <p className="px-2 py-1 text-[12px] text-faint">
                No searches yet.
              </p>
            ) : (
              searches.map((feed) => (
                <Row
                  key={feed.id}
                  active={feedId === feed.id}
                  icon={Search}
                  count={feedCounts[feed.id] ?? 0}
                  title={feed.url}
                  onClick={() => onSelectFeed(feed.id)}
                >
                  {feed.title || "Search"}
                </Row>
              ))
            )}
          </div>
        </section>

        <div className="my-2 border-t border-divider" />

        <section aria-labelledby="sidebar-labels">
          <SectionTitle
            action={
              <Button
                type="button"
                variant="icon"
                size="icon-xs"
                onClick={onAddLabel}
                aria-label="Create label"
                title="Create label"
              >
                <Plus className="size-3.5" />
              </Button>
            }
          >
            <span id="sidebar-labels">Labels</span>
          </SectionTitle>

          <div className="flex flex-col">
            {labels.length === 0 ? (
              <p className="px-2 py-1 text-[12px] text-faint">No labels yet.</p>
            ) : (
              labels.map((entry) => (
                <Row
                  key={entry.id}
                  active={label === entry.name}
                  icon={Tag}
                  onClick={() => onSelectLabel(entry.name)}
                >
                  {entry.name}
                </Row>
              ))
            )}
          </div>
        </section>
      </div>

      <div className="flex shrink-0 items-center gap-2 border-t border-divider px-3 py-2.5 text-[11px] text-faint">
        <Lock className="size-3.5 shrink-0" aria-hidden="true" />
        Everything stays on this machine.
      </div>
    </div>
  );
}
