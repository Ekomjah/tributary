"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  CircleCheck,
  Keyboard,
  Loader2,
  Menu,
  Plus,
  RefreshCw,
  Search,
  TriangleAlert,
  X,
} from "lucide-react";

import AddFeedDialog from "@/components/add-feed-dialog";
import AddLabelDialog from "@/components/add-label-dialog";
import ArticleList from "@/components/article-list";
import ArticleView from "@/components/article-view";
import Sidebar from "@/components/sidebar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { api, apiBase, ApiError } from "@/lib/api";
import { hostOf } from "@/lib/text";
import type {
  Decision,
  Item,
  ItemPage,
  ItemUpdate,
  ItemView,
  Label,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const VIEWS: ItemView[] = ["all", "unread", "starred"];
const VIEW_NAMES: Record<ItemView, string> = {
  all: "All items",
  unread: "Unread",
  starred: "Starred items",
};
const PAGE_SIZE = 100;

const SHORTCUTS: [string, string][] = [
  ["j / k", "Next / previous story"],
  ["o / Enter", "Open story"],
  ["v", "Open original"],
  ["s", "Star"],
  ["m", "Mark read / unread"],
  ["r", "Refresh feeds"],
  ["/", "Search"],
  ["Esc", "Back to the list"],
];

interface StatusMessage {
  message: string;
  error?: boolean;
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export default function Reader() {
  const queryClient = useQueryClient();

  const [view, setView] = useState<ItemView>("all");
  const [feedId, setFeedId] = useState<number | null>(null);
  const [label, setLabel] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [openItemId, setOpenItemId] = useState<number | null>(null);

  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [fetchingIds, setFetchingIds] = useState<ReadonlySet<number>>(
    () => new Set(),
  );

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [addFeedOpen, setAddFeedOpen] = useState(false);
  const [addLabelOpen, setAddLabelOpen] = useState(false);

  const searchRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLElement>(null);
  const inFlightFetches = useRef<Set<number>>(new Set());

  const showStatus = useCallback((message: string, error = false) => {
    setStatus({ message, error });
  }, []);

  const showError = useCallback(
    (error: unknown) => {
      showStatus(messageOf(error), true);
    },
    [showStatus],
  );

  const feedsQuery = useQuery({
    queryKey: ["feeds"],
    queryFn: ({ signal }) => api.listFeeds(signal),
  });

  const labelsQuery = useQuery({
    queryKey: ["labels"],
    queryFn: ({ signal }) => api.listLabels(signal),
  });

  const feeds = useMemo(() => feedsQuery.data ?? [], [feedsQuery.data]);
  const labels = useMemo(() => labelsQuery.data ?? [], [labelsQuery.data]);
  const feedKey = useMemo(
    () => feeds.map((feed) => feed.id).join(","),
    [feeds],
  );

  const countsQuery = useQuery({
    queryKey: ["counts", feedKey],
    enabled: feedsQuery.isSuccess,
    queryFn: async ({ signal }) => {
      const [allPage, unreadPage, starredPage, ...feedPages] = await Promise.all(
        [
          api.listItems({ limit: 1, signal }),
          api.listItems({ unread: true, limit: 1, signal }),
          api.listItems({ starred: true, limit: 1, signal }),
          ...feeds.map((feed) =>
            api.listItems({
              unread: true,
              feedId: feed.id,
              limit: 1,
              signal,
            }),
          ),
        ],
      );

      const feedCounts: Record<number, number> = {};
      feeds.forEach((feed, index) => {
        feedCounts[feed.id] = feedPages[index]?.total ?? 0;
      });

      const views: Record<ItemView, number> = {
        all: allPage.total,
        unread: unreadPage.total,
        starred: starredPage.total,
      };

      return { views, feeds: feedCounts };
    },
  });

  const itemsQuery = useQuery({
    queryKey: ["items", view, feedId, label, query],
    queryFn: ({ signal }) =>
      api.listItems({
        unread: view === "unread" ? true : undefined,
        starred: view === "starred" ? true : undefined,
        feedId,
        label,
        q: query || undefined,
        limit: PAGE_SIZE,
        signal,
      }),
    placeholderData: keepPreviousData,
  });

  const items = useMemo(() => itemsQuery.data?.items ?? [], [itemsQuery.data]);
  const total = itemsQuery.data?.total ?? 0;
  const loading = itemsQuery.isFetching;
  const counts = countsQuery.data?.views ?? { all: 0, unread: 0, starred: 0 };
  const feedCounts = countsQuery.data?.feeds ?? {};
  const queryError =
    feedsQuery.error ?? labelsQuery.error ?? countsQuery.error ?? itemsQuery.error;
  const queryErrorMessage = queryError ? messageOf(queryError) : null;
  const banner =
    status ??
    (queryErrorMessage ? { message: queryErrorMessage, error: true } : null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim());
    }, 280);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (!status) {
      return;
    }
    const timer = window.setTimeout(
      () => setStatus(null),
      status.error ? 6500 : 3800,
    );
    return () => window.clearTimeout(timer);
  }, [status]);

  const activeFeed = useMemo(
    () =>
      feedId === null ? null : (feeds.find((feed) => feed.id === feedId) ?? null),
    [feedId, feeds],
  );

  const feedNames = useMemo(() => {
    const names = new Map<number, string>();
    for (const feed of feeds) {
      names.set(feed.id, feed.title || hostOf(feed.url));
    }
    return names;
  }, [feeds]);

  const selectedItemId = useMemo(
    () =>
      items.some((item) => item.id === selectedId)
        ? selectedId
        : (items[0]?.id ?? null),
    [items, selectedId],
  );

  const openArticle = useMemo(
    () => items.find((item) => item.id === openItemId) ?? null,
    [items, openItemId],
  );

  const activeItem = useMemo(
    () =>
      openArticle ??
      items.find((item) => item.id === selectedItemId) ??
      null,
    [items, openArticle, selectedItemId],
  );

  const heading = query
    ? "Search results"
    : label
      ? label
      : activeFeed
        ? activeFeed.title || hostOf(activeFeed.url)
        : VIEW_NAMES[view];

  const contextLabel = query
    ? "search results"
    : label
      ? label
      : activeFeed
        ? activeFeed.title || hostOf(activeFeed.url)
        : VIEW_NAMES[view];

  const hasFilters = Boolean(query || label || feedId !== null);

  const { mutate: mutateItem } = useMutation({
    mutationFn: ({
      itemId,
      patch,
    }: {
      itemId: number;
      patch: ItemUpdate;
    }) => api.updateItem(itemId, patch),
    onSuccess: (updated) => {
      queryClient.setQueriesData<ItemPage>(
        { queryKey: ["items"] },
        (page) =>
          page
            ? {
                ...page,
                items: page.items.map((row) =>
                  row.id === updated.id ? updated : row,
                ),
              }
            : page,
      );
      void queryClient.invalidateQueries({ queryKey: ["counts"] });
    },
    onError: showError,
  });

  const { mutate: fetchArticle } = useMutation({
    mutationFn: (itemId: number) => api.fetchItemArticle(itemId),
    onMutate: (itemId) => {
      inFlightFetches.current.add(itemId);
      setFetchingIds((current) => new Set(current).add(itemId));
    },
    onSuccess: (fetched) => {
      queryClient.setQueriesData<ItemPage>(
        { queryKey: ["items"] },
        (page) =>
          page
            ? {
                ...page,
                items: page.items.map((row) =>
                  row.id === fetched.id ? { ...row, ...fetched } : row,
                ),
              }
            : page,
      );
    },
    onError: showError,
    onSettled: (_data, _error, itemId) => {
      inFlightFetches.current.delete(itemId);
      setFetchingIds((current) => {
        if (!current.has(itemId)) {
          return current;
        }
        const next = new Set(current);
        next.delete(itemId);
        return next;
      });
    },
  });

  const { mutateAsync: toggleItemLabel } = useMutation({
    mutationFn: async ({
      item,
      label: target,
    }: {
      item: Item;
      label: Label;
    }) => {
      const attached = item.labels.some((entry) => entry.id === target.id);
      if (attached) {
        await api.removeItemLabel(item.id, target.id);
        return { itemId: item.id, labelId: target.id, updated: null };
      }

      const updated = await api.addItemLabel(item.id, target.id);
      return { itemId: item.id, labelId: target.id, updated };
    },
    onSuccess: ({ itemId, labelId, updated }) => {
      queryClient.setQueriesData<ItemPage>(
        { queryKey: ["items"] },
        (page) => {
          if (!page) {
            return page;
          }
          return {
            ...page,
            items: page.items.map((row) => {
              if (row.id !== itemId) {
                return row;
              }
              if (updated) {
                return updated;
              }
              return {
                ...row,
                labels: row.labels.filter((entry) => entry.id !== labelId),
              };
            }),
          };
        },
      );
    },
    onError: showError,
  });

  const { mutate: runRefresh, isPending: refreshing } = useMutation({
    mutationFn: () => api.refreshFeeds(),
    onSuccess: (results) => {
      if (results.length === 0) {
        showStatus("Add a feed first, then refresh.");
        return;
      }

      const newItems = results.reduce(
        (sum, result) => sum + result.new_items,
        0,
      );
      const failures = results.filter((result) => result.error);
      if (failures.length > 0) {
        showStatus(
          `${plural(newItems, "new item")} · ${plural(
            failures.length,
            "feed",
          )} failed.`,
          true,
        );
      } else {
        showStatus(
          `${plural(newItems, "new item")} from ${plural(
            results.length,
            "feed",
          )}.`,
        );
      }

      void queryClient.invalidateQueries();
    },
    onError: showError,
  });

  const { mutateAsync: addFeed } = useMutation({
    mutationFn: (url: string) => api.createFeed(url),
  });

  const { mutateAsync: createLabel } = useMutation({
    mutationFn: (name: string) => api.createLabel(name),
  });

  const patchItem = useCallback(
    (item: Item, patch: ItemUpdate) => {
      mutateItem({ itemId: item.id, patch });
    },
    [mutateItem],
  );

  const openItem = useCallback(
    (item: Item) => {
      setSelectedId(item.id);
      setOpenItemId(item.id);
      if (!item.is_read) {
        patchItem(item, { is_read: true });
      }
      if (
        !item.content_full &&
        item.fetch_status === null &&
        !inFlightFetches.current.has(item.id)
      ) {
        fetchArticle(item.id);
      }
    },
    [fetchArticle, patchItem],
  );

  const toggleStar = useCallback(
    (item: Item) => {
      patchItem(item, { starred: !item.starred });
    },
    [patchItem],
  );

  const toggleRead = useCallback(
    (item: Item) => {
      patchItem(item, { is_read: !item.is_read });
    },
    [patchItem],
  );

  const toggleDecision = useCallback(
    (item: Item, decision: Decision) => {
      patchItem(item, {
        decision: item.decision === decision ? null : decision,
      });
    },
    [patchItem],
  );

  const toggleLabel = useCallback(
    (item: Item, target: Label) => {
      toggleItemLabel({ item, label: target }).catch(() => {
        // The mutation's onError already surfaced the message.
      });
    },
    [toggleItemLabel],
  );

  const clearSearch = useCallback(() => {
    setSearch("");
    setQuery("");
    setOpenItemId(null);
    searchRef.current?.focus();
  }, []);

  const selectView = useCallback((next: ItemView) => {
    setView(next);
    setFeedId(null);
    setLabel(null);
    setSearch("");
    setQuery("");
    setOpenItemId(null);
  }, []);

  const selectFeed = useCallback((next: number | null) => {
    setFeedId(next);
    setLabel(null);
    setView("all");
    setSearch("");
    setQuery("");
    setOpenItemId(null);
  }, []);

  const selectLabel = useCallback((name: string) => {
    setLabel((current) => (current === name ? null : name));
    setFeedId(null);
    setView("all");
    setSearch("");
    setQuery("");
    setOpenItemId(null);
  }, []);

  const goHome = useCallback(() => {
    setView("all");
    setFeedId(null);
    setLabel(null);
    setSearch("");
    setQuery("");
    setSelectedId(null);
    setOpenItemId(null);
  }, []);

  const refreshAll = useCallback(() => {
    if (!refreshing) {
      runRefresh();
    }
  }, [refreshing, runRefresh]);

  const submitFeed = useCallback(
    async (url: string) => {
      try {
        const { feed, result } = await addFeed(url);

        if (result.error) {
          showStatus(
            `Added the feed, but the first fetch failed: ${result.error}`,
            true,
          );
        } else {
          showStatus(
            `${result.title || feed.title || hostOf(feed.url)}: ${plural(
              result.new_items,
              "new item",
            )}.`,
          );
        }

        setView("all");
        setFeedId(feed.id);
        setLabel(null);
        setSearch("");
        setQuery("");
        setOpenItemId(null);
        void queryClient.invalidateQueries();
        return null;
      } catch (error) {
        const message = messageOf(error);
        showStatus(message, true);
        return message;
      }
    },
    [addFeed, queryClient, showStatus],
  );

  const submitLabel = useCallback(
    async (name: string) => {
      try {
        const created = await createLabel(name);
        queryClient.setQueryData<Label[]>(["labels"], (current) =>
          [...(current ?? []), created].sort((left, right) =>
            left.name.localeCompare(right.name),
          ),
        );
        showStatus(`Label “${created.name}” added.`);
        return null;
      } catch (error) {
        const message = messageOf(error);
        showStatus(message, true);
        return message;
      }
    },
    [createLabel, queryClient, showStatus],
  );

  const moveSelection = useCallback(
    (step: number) => {
      if (items.length === 0) {
        return;
      }

      const currentIndex = items.findIndex(
        (item) => item.id === selectedItemId,
      );
      const nextIndex =
        currentIndex === -1
          ? step > 0
            ? 0
            : items.length - 1
          : Math.min(items.length - 1, Math.max(0, currentIndex + step));
      const next = items[nextIndex];
      setSelectedId(next.id);
      window.requestAnimationFrame(() => {
        document
          .getElementById(`item-${next.id}`)
          ?.scrollIntoView({ block: "nearest" });
      });
    },
    [items, selectedItemId],
  );

  const navigateArticle = useCallback(
    (step: number) => {
      if (!openArticle || items.length === 0) {
        return;
      }

      const currentIndex = items.findIndex(
        (item) => item.id === openArticle.id,
      );
      if (currentIndex === -1) {
        return;
      }

      const nextIndex = Math.min(
        items.length - 1,
        Math.max(0, currentIndex + step),
      );
      if (nextIndex === currentIndex) {
        return;
      }
      openItem(items[nextIndex]);
    },
    [items, openArticle, openItem],
  );

  const listScope = `${view}|${feedId ?? ""}|${label ?? ""}|${query}`;

  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0 });
  }, [listScope, openItemId]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || addFeedOpen || addLabelOpen || drawerOpen) {
        return;
      }

      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        if (event.key === "Escape") {
          target.blur();
        }
        return;
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      const key = event.key.toLowerCase();

      if (key === "/") {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }

      if (key === "1") {
        event.preventDefault();
        selectView("all");
        return;
      }

      if (key === "2") {
        event.preventDefault();
        selectView("unread");
        return;
      }

      if (key === "3") {
        event.preventDefault();
        selectView("starred");
        return;
      }

      if (key === "r") {
        event.preventDefault();
        void refreshAll();
        return;
      }

      if (event.key === "Escape") {
        if (openArticle) {
          event.preventDefault();
          setOpenItemId(null);
        }
        return;
      }

      if (key === "j" || key === "k") {
        event.preventDefault();
        if (openArticle) {
          navigateArticle(key === "j" ? 1 : -1);
        } else {
          moveSelection(key === "j" ? 1 : -1);
        }
        return;
      }

      if (!activeItem) {
        return;
      }

      if (key === "o" || event.key === "Enter") {
        if (!openArticle) {
          event.preventDefault();
          openItem(activeItem);
        }
        return;
      }

      if (key === "v" && activeItem.link) {
        event.preventDefault();
        window.open(activeItem.link, "_blank", "noopener,noreferrer");
        return;
      }

      if (key === "s") {
        event.preventDefault();
        void patchItem(activeItem, { starred: !activeItem.starred });
        return;
      }

      if (key === "m") {
        event.preventDefault();
        void patchItem(activeItem, { is_read: !activeItem.is_read });
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    activeItem,
    addFeedOpen,
    addLabelOpen,
    drawerOpen,
    moveSelection,
    navigateArticle,
    openArticle,
    openItem,
    patchItem,
    refreshAll,
    selectView,
  ]);

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink">
      <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-divider bg-canvas px-4 py-2.5 min-[700px]:h-14 min-[700px]:flex-nowrap min-[700px]:gap-4 min-[700px]:py-0">
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            variant="icon"
            size="icon"
            className="min-[700px]:hidden"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open feeds and labels"
          >
            <Menu className="size-4" />
          </Button>
          <button
            type="button"
            onClick={goHome}
            className="text-[20px] font-bold leading-none text-danger hover:opacity-80"
          >
            Tributary
          </button>
        </div>

        <div
          role="search"
          className="relative order-3 w-full min-[700px]:order-none min-[700px]:mx-auto min-[700px]:max-w-[620px] min-[700px]:flex-1"
        >
          <Search
            className="pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-faint"
            aria-hidden="true"
          />
          <Input
            ref={searchRef}
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              if (openItemId !== null) {
                setOpenItemId(null);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.currentTarget.blur();
              }
            }}
            placeholder="Search Reader"
            aria-label="Search items"
            autoComplete="off"
            spellCheck={false}
            className="pl-8 pr-8 [&::-webkit-search-cancel-button]:hidden"
          />
          {search && (
            <Button
              type="button"
              variant="icon"
              size="icon-xs"
              className="absolute right-1 top-1/2 -translate-y-1/2"
              onClick={clearSearch}
              aria-label="Clear search"
            >
              <X className="size-3.5" />
            </Button>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <Popover>
            <PopoverTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="gap-1.5 px-2 text-[11px] text-muted"
                />
              }
            >
              <Keyboard className="size-3.5" />
              <span className="hidden lg:inline">Shortcuts</span>
            </PopoverTrigger>
            <PopoverContent className="w-72 p-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-muted">
                Keyboard
              </p>
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[12px]">
                {SHORTCUTS.map(([keys, description]) => (
                  <div className="contents" key={keys}>
                    <dt>
                      <kbd className="rounded-sm border border-line bg-chrome px-1.5 py-0.5 font-mono text-[10px] text-ink">
                        {keys}
                      </kbd>
                    </dt>
                    <dd className="self-center text-muted">{description}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 break-all border-t border-divider pt-2 font-mono text-[10px] text-faint">
                {apiBase}
              </p>
            </PopoverContent>
          </Popover>
        </div>
      </header>

      <div className="flex min-h-10 shrink-0 items-center justify-between gap-3 border-b border-divider bg-canvas px-4 max-[700px]:px-3">
        <div className="flex min-w-0 items-center gap-2">
          <Button
            type="button"
            variant="primary"
            size="sm"
            className="max-[700px]:h-8"
            onClick={() => setAddFeedOpen(true)}
          >
            <Plus className="size-3.5" />
            Add feed
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="gap-1.5 max-[700px]:h-8"
            onClick={() => void refreshAll()}
            disabled={refreshing}
          >
            {refreshing ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="size-3.5" aria-hidden="true" />
            )}
            <span className="max-[420px]:hidden">
              {refreshing ? "Refreshing…" : "Refresh"}
            </span>
          </Button>
        </div>

        <nav
          aria-label="Views"
          className="flex shrink-0 items-center gap-4 text-[13px] max-[700px]:gap-3 max-[700px]:text-[12px]"
        >
          {VIEWS.map((entry) => {
            const active = view === entry;
            return (
              <button
                key={entry}
                type="button"
                onClick={() => selectView(entry)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "whitespace-nowrap",
                  active
                    ? "font-bold text-ink underline underline-offset-4"
                    : "text-muted hover:text-ink",
                )}
              >
                {VIEW_NAMES[entry]}
              </button>
            );
          })}
        </nav>
      </div>

      {banner && (
        <div
          role={banner.error ? "alert" : "status"}
          aria-live={banner.error ? "assertive" : "polite"}
          className={cn(
            "flex shrink-0 items-start gap-2 border-b border-divider bg-canvas px-4 py-1.5 text-[12px] leading-5 max-[700px]:px-3",
            banner.error ? "text-danger" : "text-muted",
          )}
        >
          {banner.error ? (
            <TriangleAlert
              className="mt-0.5 size-3.5 shrink-0"
              aria-hidden="true"
            />
          ) : (
            <CircleCheck
              className="mt-0.5 size-3.5 shrink-0 text-success"
              aria-hidden="true"
            />
          )}
          <span className="min-w-0 flex-1">{banner.message}</span>
          {status && (
            <Button
              type="button"
              variant="icon"
              size="icon-xs"
              className="-mr-1 -mt-0.5 text-faint hover:text-ink"
              onClick={() => setStatus(null)}
              aria-label="Dismiss message"
            >
              <X className="size-3.5" />
            </Button>
          )}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 min-[700px]:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="hidden min-h-0 border-r border-divider min-[700px]:block">
          <Sidebar
            feeds={feeds}
            feedCounts={feedCounts}
            labels={labels}
            view={view}
            feedId={feedId}
            label={label}
            viewCounts={counts}
            onSelectView={selectView}
            onSelectFeed={selectFeed}
            onSelectLabel={selectLabel}
            onAddFeed={() => setAddFeedOpen(true)}
            onAddLabel={() => setAddLabelOpen(true)}
          />
        </aside>

        <main
          ref={contentRef}
          className="min-h-0 overflow-y-auto overscroll-contain bg-canvas"
        >
          {openArticle ? (
            <ArticleView
              item={openArticle}
              feedName={
                feedNames.get(openArticle.feed_id) ?? "Unknown feed"
              }
              feedCount={feedCounts[openArticle.feed_id] ?? 0}
              labels={labels}
              contextLabel={contextLabel}
              fetching={fetchingIds.has(openArticle.id)}
              onBack={() => setOpenItemId(null)}
              onToggleStar={toggleStar}
              onToggleRead={toggleRead}
              onToggleDecision={toggleDecision}
              onToggleLabel={toggleLabel}
              onSelectFeed={selectFeed}
            />
          ) : (
            <ArticleList
              items={items}
              total={total}
              loading={loading}
              heading={heading}
              query={query}
              view={view}
              hasFeeds={feeds.length > 0}
              hasFilters={hasFilters}
              feedNames={feedNames}
              feedCounts={feedCounts}
              labels={labels}
              selectedId={selectedItemId}
              onOpen={openItem}
              onToggleStar={toggleStar}
              onToggleRead={toggleRead}
              onToggleLabel={toggleLabel}
              onSelectFeed={selectFeed}
              onSelectView={selectView}
              onAddFeed={() => setAddFeedOpen(true)}
              onClearSearch={clearSearch}
            />
          )}
        </main>
      </div>

      <AddFeedDialog
        open={addFeedOpen}
        onOpenChange={setAddFeedOpen}
        onDiscover={(url) => api.discoverFeeds(url)}
        onAdd={submitFeed}
      />
      <AddLabelDialog
        open={addLabelOpen}
        onOpenChange={setAddLabelOpen}
        onSubmit={submitLabel}
      />

      <Dialog open={drawerOpen} onOpenChange={setDrawerOpen}>
        <DialogContent
          showCloseButton={false}
          className="left-0 top-0 h-dvh w-[280px] max-w-[calc(100vw-48px)] translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 border-r border-divider bg-sidebar p-0"
        >
          <div className="flex h-full flex-col">
            <DialogHeader className="min-h-12 justify-between px-3 pr-2">
              <DialogTitle className="text-[13px]">
                Feeds & labels
              </DialogTitle>
              <DialogClose className="grid size-8 place-items-center rounded-sm text-muted hover:bg-[#e8e8e8] hover:text-ink">
                <X className="size-4" aria-hidden="true" />
                <span className="sr-only">Close</span>
              </DialogClose>
            </DialogHeader>
            <div className="min-h-0 flex-1">
              <Sidebar
                feeds={feeds}
                feedCounts={feedCounts}
                labels={labels}
                view={view}
                feedId={feedId}
                label={label}
                viewCounts={counts}
                onSelectView={(next) => {
                  selectView(next);
                  setDrawerOpen(false);
                }}
                onSelectFeed={(next) => {
                  selectFeed(next);
                  setDrawerOpen(false);
                }}
                onSelectLabel={(next) => {
                  selectLabel(next);
                  setDrawerOpen(false);
                }}
                onAddFeed={() => {
                  setDrawerOpen(false);
                  setAddFeedOpen(true);
                }}
                onAddLabel={() => {
                  setDrawerOpen(false);
                  setAddLabelOpen(true);
                }}
              />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
