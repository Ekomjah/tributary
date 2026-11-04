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
  type InfiniteData,
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
import AccountMenu from "@/components/account-menu";
import DeleteFeedDialog from "@/components/delete-feed-dialog";
import ShareDialog from "@/components/share-dialog";
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
import { useAuthSession } from "@/lib/auth";
import { useDelayedFlag } from "@/components/feeds/use-slow-loading";
import { useItemMutations } from "@/components/feeds/use-item-mutations";
import { useLabelMutations } from "@/components/feeds/use-label-mutations";
import { optimisticItem } from "@/lib/optimistic";
import {
  feedsHref,
  itemsQueryOptions,
  mapItemPages,
  readScope,
  sameScope,
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

interface StatusAction {
  label: string;
  run: () => void;
}

interface StatusMessage {
  message: string;
  error?: boolean;
  action?: StatusAction;
}

interface PendingNavigation {
  scope: FeedsScope;
  since: number;
}

interface FeedsContextValue {
  scope: FeedsScope;
  effectiveScope: FeedsScope;
  pendingScope: FeedsScope | null;
  pendingSince: number | null;
  beginScopeNavigation: (next: FeedsScope) => void;
  completeScopeNavigation: () => void;
  prefetchScope: (next: FeedsScope) => void;
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
  ingesting: boolean;
  scrollRef: React.RefObject<HTMLElement | null>;
  showStatus: (message: string, error?: boolean) => void;
  showError: (error: unknown) => void;
  refreshAll: () => void;
  refreshing: boolean;
  submitFeed: (url: string) => Promise<string | null>;
  submitLabel: (name: string) => Promise<string | null>;
  patchItem: (
    item: Item,
    patch: ItemUpdate,
    options?: { silent?: boolean },
  ) => void;
  fetchArticle: (itemId: number, options?: { force?: boolean }) => void;
  fetchingIds: ReadonlySet<number>;
  toggleStar: (item: Item) => void;
  toggleRead: (item: Item) => void;
  toggleDecision: (item: Item, decision: Decision) => void;
  toggleLabel: (item: Item, label: Label) => void;
  sharingEnabled: boolean;
  openShare: (item: Item) => void;
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
    // While a feed is ingesting in the background, poll until every worker
    // finishes so the list can pick up the entries as they land.
    refetchInterval: (query) =>
      query.state.data?.some((feed) => feed.ingest_state === "pending")
        ? 1500
        : false,
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
  const auth = useAuthSession();
  const sharingEnabled = auth.mode === "cloud" && auth.isAuthenticated;
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
  const [shareItem, setShareItem] = useState<Item | null>(null);
  const [pending, setPending] = useState<PendingNavigation | null>(null);

  const effectiveScope = pending?.scope ?? scope;
  const slow = useDelayedFlag(pending !== null, 1500);

  const searchRef = useRef<HTMLInputElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const searchOrigin = useRef(pathname);
  const lastScopeQuery = useRef(scope.query);
  const inFlightFetches = useRef<Set<number>>(new Set());

  const { feedsQuery, labelsQuery, countsQuery, feeds, labels } =
    useFeedsData();

  const pendingFeedIds = useMemo(
    () =>
      new Set(
        feeds
          .filter((feed) => feed.ingest_state === "pending")
          .map((feed) => feed.id),
      ),
    [feeds],
  );
  const ingesting = pendingFeedIds.size > 0;

  // Invalidate the list once when an ingestion that we watched leaves the
  // pending state, so the items stored by the last background batches appear.
  const previousPendingFeedIds = useRef<Set<number>>(new Set());
  useEffect(() => {
    const settled = [...previousPendingFeedIds.current].filter(
      (feedId) => !pendingFeedIds.has(feedId),
    );
    previousPendingFeedIds.current = pendingFeedIds;
    if (settled.length === 0) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: ["items"] });
    void queryClient.invalidateQueries({ queryKey: ["counts"] });
    void queryClient.invalidateQueries({ queryKey: ["item"] });
  }, [pendingFeedIds, queryClient]);

  // A fast worker can finish between two feed polls, before the list ever sees
  // it as "pending". Invalidate once more shortly after a deferred refresh so
  // those last batches still appear. Slower workers are covered by polling.
  const settleDeferredIngest = useCallback(() => {
    window.setTimeout(() => {
      void queryClient.invalidateQueries({ queryKey: ["feeds"] });
      void queryClient.invalidateQueries({ queryKey: ["items"] });
      void queryClient.invalidateQueries({ queryKey: ["counts"] });
      void queryClient.invalidateQueries({ queryKey: ["item"] });
    }, 2000);
  }, [queryClient]);

  const feedNames = useMemo(() => {
    const names = new Map<number, string>();
    for (const feed of feeds) {
      names.set(feed.id, feed.title || hostOf(feed.url));
    }
    return names;
  }, [feeds]);

  const currentFeed = useMemo(
    () => feeds.find((feed) => feed.id === effectiveScope.feedId) ?? null,
    [effectiveScope.feedId, feeds],
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

  const showRetryableError = useCallback(
    (error: unknown, retry: () => void) => {
      setStatus({
        message: messageOf(error),
        error: true,
        action: { label: "Retry", run: retry },
      });
    },
    [],
  );

  const queryError =
    feedsQuery.error ?? labelsQuery.error ?? countsQuery.error;
  const banner =
    status ??
    (queryError ? { message: messageOf(queryError), error: true } : null);
  const bannerAction = status?.action ?? null;

  const beginScopeNavigation = useCallback(
    (next: FeedsScope) => {
      if (pathname === "/feeds" && sameScope(next, scope)) {
        setPending(null);
        return;
      }
      setPending({ scope: next, since: Date.now() });
    },
    [pathname, scope],
  );

  const completeScopeNavigation = useCallback(() => {
    setPending(null);
  }, []);

  const prefetchScope = useCallback(
    (next: FeedsScope) => {
      if (sameScope(next, scope)) {
        return;
      }
      const options = itemsQueryOptions(next);
      if (queryClient.getQueryData(options.queryKey)) {
        return;
      }
      void queryClient.prefetchInfiniteQuery(options);
    },
    [queryClient, scope],
  );

  const navigateToScope = useCallback(
    (
      next: FeedsScope,
      options?: { replace?: boolean; hash?: string },
    ) => {
      beginScopeNavigation(next);
      const href = `${feedsHref(next)}${options?.hash ?? ""}`;
      if (options?.replace) {
        router.replace(href, { scroll: false });
      } else {
        router.push(href);
      }
    },
    [beginScopeNavigation, router],
  );

  useEffect(() => {
    function onPopState() {
      setPending(null);
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (pathname === "/feeds") {
      return;
    }
    const timer = window.setTimeout(() => setPending(null), 0);
    return () => window.clearTimeout(timer);
  }, [pathname]);

  useEffect(() => {
    if (!status || status.action) {
      // A failed mutation stays until the user retries or dismisses it.
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

  const {
    patchItem,
    toggleStar,
    toggleRead,
    toggleDecision,
    toggleLabel,
  } = useItemMutations({ onError: showRetryableError });

  const { mutate: runFetchArticle } = useMutation({
    mutationFn: ({
      itemId,
      force = false,
    }: {
      itemId: number;
      force?: boolean;
    }) => api.fetchItemArticle(itemId, force),
    onMutate: ({ itemId }) => {
      inFlightFetches.current.add(itemId);
      setFetchingIds((current) => new Set(current).add(itemId));
    },
    onSuccess: (fetched) => {
      // A background fetch can land while a toggle is still in flight; layer
      // the optimistic intent so it cannot undo the user's change.
      queryClient.setQueriesData<InfiniteData<ItemPage>>(
        { queryKey: ["items"] },
        (data) =>
          mapItemPages(data, (row) =>
            row.id === fetched.id
              ? optimisticItem({ ...row, ...fetched })
              : row,
          ),
      );
      queryClient.setQueryData<Item>(["item", fetched.id], (current) =>
        current ? optimisticItem({ ...current, ...fetched }) : current,
      );
    },
    onError: showError,
    onSettled: (_data, _error, variables) => {
      const itemId = variables.itemId;
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

  const fetchArticle = useCallback(
    (itemId: number, options?: { force?: boolean }) => {
      runFetchArticle({ itemId, force: options?.force ?? false });
    },
    [runFetchArticle],
  );

  const { mutate: runRefresh, isPending: refreshingAll } = useMutation({
    mutationFn: () => api.refreshFeeds(),
    onSuccess: (results) => {
      if (results.length === 0) {
        showStatus("Add a feed first, then refresh.");
        return;
      }

      if (results.some((result) => result.pending_entries > 0)) {
        settleDeferredIngest();
      }
      const failures = results.filter((result) => result.error);
      if (failures.length > 0) {
        showStatus(
          `${plural(failures.length, "feed")} could not be refreshed.`,
          true,
        );
      } else {
        showStatus("Feeds refreshed.");
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
        showStatus(`“${result.title || "Pipe feed"}” refreshed.`);
      }
      void queryClient.invalidateQueries();
    },
    onError: showError,
  });

  const { mutateAsync: addFeed } = useMutation({
    mutationFn: (url: string) => api.createFeed(url),
  });

  const openShare = useCallback((item: Item) => {
    setShareItem(item);
  }, []);

  const refreshAll = useCallback(() => {
    if (currentFeed?.kind === "shared") {
      showStatus("Shared articles arrive when someone shares them.");
      return;
    }
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
    showStatus,
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
          if (result.pending_entries > 0) {
            settleDeferredIngest();
          }
          showStatus(
            `Added “${result.title || feed.title || hostOf(feed.url)}”.`,
          );
        }

        queryClient.setQueryData<Feed[]>(["feeds"], (current) =>
          current?.some((entry) => entry.id === feed.id)
            ? current
            : [...(current ?? []), feed],
        );
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
    [addFeed, navigateToScope, queryClient, settleDeferredIngest, showStatus],
  );

  const { createLabel: submitLabel } = useLabelMutations({
    onStatus: showStatus,
    onError: showRetryableError,
  });

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
              : feed.kind === "shared"
                ? `Removed “${name}” and its shared articles.`
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
    addFeedOpen ||
    addLabelOpen ||
    drawerOpen ||
    feedToDelete !== null ||
    shareItem !== null;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || shortcutsBlocked) {
        return;
      }

      // Let an open dialog handle its own keys instead of navigating behind it.
      if (
        event.target instanceof Element &&
        event.target.closest('[data-slot="dialog-content"]')
      ) {
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
      effectiveScope,
      pendingScope: pending?.scope ?? null,
      pendingSince: pending?.since ?? null,
      beginScopeNavigation,
      completeScopeNavigation,
      prefetchScope,
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
      ingesting,
      scrollRef: mainRef,
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
      sharingEnabled,
      openShare,
      openAddFeed: () => setAddFeedOpen(true),
      openAddLabel: () => setAddLabelOpen(true),
      shortcutsBlocked,
      scrollToTop,
    }),
    [
      beginScopeNavigation,
      clearSearch,
      completeScopeNavigation,
      counts,
      effectiveScope,
      feedCounts,
      feedNames,
      feeds,
      fetchArticle,
      fetchingIds,
      ingesting,
      labels,
      navigateToScope,
      openShare,
      patchItem,
      pending,
      prefetchScope,
      refreshAll,
      refreshing,
      scope,
      scrollToTop,
      search,
      selectFeed,
      selectLabel,
      selectView,
      sharingEnabled,
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
              scroll={false}
              onNavigate={() =>
                beginScopeNavigation({
                  view: "all",
                  feedId: null,
                  label: null,
                  query: "",
                })
              }
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
                const next = event.target.value;
                setSearch(next);
                if (
                  next === scope.query &&
                  pending &&
                  pending.scope.query !== "" &&
                  pending.scope.query !== scope.query
                ) {
                  completeScopeNavigation();
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
            <AccountMenu />
          </div>
        </header>

        <div className="relative flex min-h-10 shrink-0 items-center justify-between gap-3 border-b border-divider bg-canvas px-4 max-[700px]:px-3">
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
              const target: FeedsScope = {
                view: entry,
                feedId: null,
                label: null,
                query: "",
              };
              const active = effectiveScope.view === entry;
              return (
                <Link
                  key={entry}
                  href={feedsHref(target)}
                  scroll={false}
                  prefetch={false}
                  onNavigate={() => beginScopeNavigation(target)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "whitespace-nowrap active:text-accent-dark",
                    active
                      ? "font-bold text-ink underline underline-offset-4"
                      : "text-muted hover:text-ink",
                  )}
                >
                  {VIEW_NAMES[entry]}
                </Link>
              );
            })}
          </nav>

          <span
            aria-hidden="true"
            className={cn(
              "pointer-events-none absolute inset-x-0 -bottom-px h-0.5 transition-colors duration-100",
              pending ? (slow ? "bg-warn" : "bg-accent") : "bg-transparent",
            )}
          />
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
            {bannerAction && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="-my-1 shrink-0"
                onClick={() => {
                  setStatus(null);
                  bannerAction.run();
                }}
              >
                {bannerAction.label}
              </Button>
            )}
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
              view={effectiveScope.view}
              feedId={effectiveScope.feedId}
              label={effectiveScope.label}
              viewCounts={counts}
              pendingScope={pending?.scope ?? null}
              onBeginNavigate={beginScopeNavigation}
              onPrefetchScope={prefetchScope}
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
        <ShareDialog
          item={shareItem}
          open={shareItem !== null}
          onOpenChange={(open) => {
            if (!open) {
              setShareItem(null);
            }
          }}
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
                  view={effectiveScope.view}
                  feedId={effectiveScope.feedId}
                  label={effectiveScope.label}
                  viewCounts={counts}
                  pendingScope={pending?.scope ?? null}
                  onBeginNavigate={beginScopeNavigation}
                  onPrefetchScope={prefetchScope}
                  onNavigated={() => setDrawerOpen(false)}
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
