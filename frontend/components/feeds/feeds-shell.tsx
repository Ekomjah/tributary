"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
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
import DeleteFeedDialog from "@/components/delete-feed-dialog";
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
import {
  feedsHref,
  readScope,
  scopeAfterFeedDelete,
  VIEW_NAMES,
  VIEWS,
  type FeedsScope,
} from "@/lib/feeds";
import { hostOf } from "@/lib/text";
import type {
  Decision,
  Feed,
  Item,
  ItemPage,
  ItemUpdate,
  ItemView,
  Label,
} from "@/lib/types";
import { cn } from "@/lib/utils";

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

interface FeedsContextValue {
  scope: FeedsScope;
  navigateToScope: (
    next: FeedsScope,
    options?: { replace?: boolean; hash?: string },
  ) => void;
  search: string;
  setSearch: (value: string) => void;
  searchRef: React.RefObject<HTMLInputElement | null>;
  clearSearch: () => void;
  selectView: (view: ItemView) => void;
  selectFeed: (feedId: number | null) => void;
  selectLabel: (name: string) => void;
  feeds: Feed[];
  labels: Label[];
  feedNames: Map<number, string>;
  feedCounts: Record<number, number>;
  viewCounts: Record<ItemView, number>;
  showStatus: (message: string, error?: boolean) => void;
  showError: (error: unknown) => void;
  refreshAll: () => void;
  refreshing: boolean;
  submitFeed: (url: string) => Promise<string | null>;
  submitLabel: (name: string) => Promise<string | null>;
  patchItem: (item: Item, patch: ItemUpdate) => void;
  fetchArticle: (itemId: number) => void;
  fetchingIds: ReadonlySet<number>;
  toggleStar: (item: Item) => void;
  toggleRead: (item: Item) => void;
  toggleDecision: (item: Item, decision: Decision) => void;
  toggleLabel: (item: Item, label: Label) => void;
  openAddFeed: () => void;
  openAddLabel: () => void;
  shortcutsBlocked: boolean;
  scrollToTop: () => void;
}

const FeedsContext = createContext<FeedsContextValue | null>(null);

function useFeedsData() {
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

  return { feedsQuery, labelsQuery, countsQuery, feeds, labels };
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

export function useFeeds(): FeedsContextValue {
  const value = useContext(FeedsContext);
  if (value === null) {
    throw new Error("useFeeds must be used inside FeedsShell");
  }
  return value;
}

export default function FeedsShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchKey = searchParams.toString();
  const scope = useMemo(
    () => readScope(new URLSearchParams(searchKey)),
    [searchKey],
  );

  const [search, setSearch] = useState(scope.query);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [fetchingIds, setFetchingIds] = useState<ReadonlySet<number>>(
    () => new Set(),
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [addFeedOpen, setAddFeedOpen] = useState(false);
  const [addLabelOpen, setAddLabelOpen] = useState(false);
  const [feedToDelete, setFeedToDelete] = useState<Feed | null>(null);

  const searchRef = useRef<HTMLInputElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const searchOrigin = useRef(pathname);
  const lastScopeQuery = useRef(scope.query);
  const inFlightFetches = useRef<Set<number>>(new Set());

  const { feedsQuery, labelsQuery, countsQuery, feeds, labels } =
    useFeedsData();

  const feedNames = useMemo(() => {
    const names = new Map<number, string>();
    for (const feed of feeds) {
      names.set(feed.id, feed.title || hostOf(feed.url));
    }
    return names;
  }, [feeds]);

  const currentFeed = useMemo(
    () => feeds.find((feed) => feed.id === scope.feedId) ?? null,
    [feeds, scope.feedId],
  );

  const counts = useMemo<Record<ItemView, number>>(
    () =>
      countsQuery.data?.views ?? {
        all: 0,
        unread: 0,
        starred: 0,
      },
    [countsQuery.data],
  );
  const feedCounts = useMemo<Record<number, number>>(
    () => countsQuery.data?.feeds ?? {},
    [countsQuery.data],
  );

  const showStatus = useCallback((message: string, error = false) => {
    setStatus({ message, error });
  }, []);

  const showError = useCallback(
    (error: unknown) => {
      showStatus(messageOf(error), true);
    },
    [showStatus],
  );

  const queryError =
    feedsQuery.error ?? labelsQuery.error ?? countsQuery.error;
  const banner =
    status ??
    (queryError ? { message: messageOf(queryError), error: true } : null);

  const navigateToScope = useCallback(
    (
      next: FeedsScope,
      options?: { replace?: boolean; hash?: string },
    ) => {
      const href = `${feedsHref(next)}${options?.hash ?? ""}`;
      if (options?.replace) {
        router.replace(href, { scroll: false });
      } else {
        router.push(href);
      }
    },
    [router],
  );

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

  useEffect(() => {
    if (scope.query === search) {
      return;
    }

    if (searchOrigin.current !== pathname) {
      return;
    }

    const timer = window.setTimeout(() => {
      navigateToScope({ ...scope, query: search.trim() }, { replace: true });
    }, 280);
    return () => window.clearTimeout(timer);
  }, [navigateToScope, pathname, scope, search]);

  useEffect(() => {
    if (scope.query === lastScopeQuery.current) {
      return;
    }
    lastScopeQuery.current = scope.query;
    setSearch(scope.query);
    searchOrigin.current = pathname;
  }, [pathname, scope.query]);

  const clearSearch = useCallback(() => {
    setSearch("");
    searchOrigin.current = pathname;
    navigateToScope({ ...scope, query: "" }, { replace: true });
    searchRef.current?.focus();
  }, [navigateToScope, pathname, scope]);

  const selectView = useCallback(
    (view: ItemView) => {
      navigateToScope({ view, feedId: null, label: null, query: "" });
    },
    [navigateToScope],
  );

  const selectFeed = useCallback(
    (feedId: number | null) => {
      navigateToScope({
        view: "all",
        feedId,
        label: null,
        query: "",
      });
    },
    [navigateToScope],
  );

  const selectLabel = useCallback(
    (name: string) => {
      navigateToScope({
        view: "all",
        feedId: null,
        label: scope.label === name ? null : name,
        query: "",
      });
    },
    [navigateToScope, scope.label],
  );

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
      queryClient.setQueryData<Item>(["item", updated.id], updated);
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
      queryClient.setQueryData<Item>(["item", fetched.id], (current) =>
        current ? { ...current, ...fetched } : current,
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
      queryClient.setQueryData<Item>(["item", itemId], (current) => {
        if (!current) {
          return current;
        }
        if (updated) {
          return updated;
        }
        return {
          ...current,
          labels: current.labels.filter((entry) => entry.id !== labelId),
        };
      });
    },
    onError: showError,
  });

  const { mutate: runRefresh, isPending: refreshingAll } = useMutation({
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

  const { mutate: runPipeRefresh, isPending: refreshingPipe } = useMutation({
    mutationFn: (feedId: number) => api.refreshFeed(feedId),
    onSuccess: (result) => {
      if (result.error) {
        showStatus(
          `“${result.title || "Pipe feed"}” did not refresh: ${result.error}`,
          true,
        );
      } else {
        showStatus(
          `“${result.title || "Pipe feed"}” refreshed: ${plural(
            result.new_items,
            "item",
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

  const refreshAll = useCallback(() => {
    if (currentFeed?.kind === "pipe") {
      if (!refreshingPipe) {
        runPipeRefresh(currentFeed.id);
      }
      return;
    }
    if (!refreshingAll) {
      runRefresh();
    }
  }, [
    currentFeed,
    refreshingAll,
    refreshingPipe,
    runPipeRefresh,
    runRefresh,
  ]);

  const refreshing = refreshingAll || refreshingPipe;

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

        navigateToScope({
          view: "all",
          feedId: feed.id,
          label: null,
          query: "",
        });
        void queryClient.invalidateQueries();
        return null;
      } catch (error) {
        const message = messageOf(error);
        showStatus(message, true);
        return message;
      }
    },
    [addFeed, navigateToScope, queryClient, showStatus],
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

  const deleteFeed = useCallback(
    async (feed: Feed) => {
      try {
        await api.deleteFeed(feed.id);
        const name = feed.title || hostOf(feed.url);
        showStatus(
          feed.kind === "search"
            ? `Removed “${name}”.`
            : feed.kind === "pipe"
              ? `Removed “${name}” from the reader.`
              : `Deleted “${name}” and its articles.`,
        );

        const nextScope = scopeAfterFeedDelete(scope, feed.id);
        if (nextScope) {
          navigateToScope(nextScope);
        }

        void queryClient.invalidateQueries({ queryKey: ["feeds"] });
        void queryClient.invalidateQueries({ queryKey: ["counts"] });
        void queryClient.invalidateQueries({ queryKey: ["items"] });
        void queryClient.invalidateQueries({ queryKey: ["item"] });
        return null;
      } catch (error) {
        return messageOf(error);
      }
    },
    [navigateToScope, queryClient, scope, showStatus],
  );

  const scrollToTop = useCallback(() => {
    mainRef.current?.scrollTo({ top: 0 });
  }, []);

  const shortcutsBlocked =
    addFeedOpen || addLabelOpen || drawerOpen || feedToDelete !== null;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || shortcutsBlocked) {
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
        refreshAll();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [refreshAll, selectView, shortcutsBlocked]);

  const value = useMemo<FeedsContextValue>(
    () => ({
      scope,
      navigateToScope,
      search,
      setSearch,
      searchRef,
      clearSearch,
      selectView,
      selectFeed,
      selectLabel,
      feeds,
      labels,
      feedNames,
      feedCounts,
      viewCounts: counts,
      showStatus,
      showError,
      refreshAll,
      refreshing,
      submitFeed,
      submitLabel,
      patchItem,
      fetchArticle,
      fetchingIds,
      toggleStar,
      toggleRead,
      toggleDecision,
      toggleLabel,
      openAddFeed: () => setAddFeedOpen(true),
      openAddLabel: () => setAddLabelOpen(true),
      shortcutsBlocked,
      scrollToTop,
    }),
    [
      clearSearch,
      counts,
      feedCounts,
      feedNames,
      feeds,
      fetchArticle,
      fetchingIds,
      labels,
      navigateToScope,
      patchItem,
      refreshAll,
      refreshing,
      scope,
      scrollToTop,
      search,
      selectFeed,
      selectLabel,
      selectView,
      shortcutsBlocked,
      showError,
      showStatus,
      submitFeed,
      submitLabel,
      toggleDecision,
      toggleLabel,
      toggleRead,
      toggleStar,
    ],
  );

  return (
    <FeedsContext.Provider value={value}>
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
            <Link
              href="/feeds"
              className="text-[20px] font-bold leading-none text-danger hover:no-underline hover:opacity-80"
            >
              Tributary
            </Link>
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
                searchOrigin.current = pathname;
                setSearch(event.target.value);
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
              onClick={refreshAll}
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
              const active = scope.view === entry;
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
              view={scope.view}
              feedId={scope.feedId}
              label={scope.label}
              viewCounts={counts}
              onSelectView={selectView}
              onSelectFeed={selectFeed}
              onSelectLabel={selectLabel}
              onAddFeed={() => setAddFeedOpen(true)}
              onAddLabel={() => setAddLabelOpen(true)}
              onDeleteFeed={setFeedToDelete}
            />
          </aside>

          <main
            ref={mainRef}
            className="min-h-0 overflow-y-auto overscroll-contain bg-canvas"
          >
            {children}
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
        <DeleteFeedDialog
          feed={feedToDelete}
          onOpenChange={(open) => {
            if (!open) {
              setFeedToDelete(null);
            }
          }}
          onConfirm={() =>
            feedToDelete ? deleteFeed(feedToDelete) : Promise.resolve(null)
          }
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
                  view={scope.view}
                  feedId={scope.feedId}
                  label={scope.label}
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
                  onDeleteFeed={(feed) => {
                    setDrawerOpen(false);
                    setFeedToDelete(feed);
                  }}
                />
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </FeedsContext.Provider>
  );
}
