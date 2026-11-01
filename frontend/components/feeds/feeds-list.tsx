"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import ArticleList from "@/components/article-list";
import { useFeeds } from "@/components/feeds/feeds-shell";
import {
  articleHref,
  itemIdFromHash,
  itemsQueryOptions,
  sameScope,
  scopeDescription,
  scopeKey,
  scopeLabel,
} from "@/lib/feeds";
import type { Item } from "@/lib/types";

export default function FeedsList() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const {
    scope,
    effectiveScope,
    pendingScope,
    pendingSince,
    navigateToScope,
    completeScopeNavigation,
    feeds,
    labels,
    feedNames,
    feedCounts,
    toggleStar,
    toggleRead,
    toggleLabel,
    selectFeed,
    selectView,
    openAddFeed,
    clearSearch,
    shortcutsBlocked,
    scrollToTop,
  } = useFeeds();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [displayedScope, setDisplayedScope] = useState(effectiveScope);
  const key = scopeKey(effectiveScope);
  const lastScopeKey = useRef(key);
  const restoredScope = useRef<string | null>(null);

  const itemsQuery = useQuery({
    ...itemsQueryOptions(effectiveScope),
    placeholderData: keepPreviousData,
  });
  const { refetch: refetchItems } = itemsQuery;

  const items = useMemo(() => itemsQuery.data?.items ?? [], [itemsQuery.data]);
  const total = itemsQuery.data?.total ?? 0;
  const loading = itemsQuery.isPending;
  const busy = itemsQuery.isFetching || pendingScope !== null;

  const hashItemId =
    typeof window === "undefined"
      ? null
      : itemIdFromHash(window.location.hash);

  const selectedItemId = useMemo(() => {
    if (selectedId !== null && items.some((item) => item.id === selectedId)) {
      return selectedId;
    }
    if (hashItemId !== null && items.some((item) => item.id === hashItemId)) {
      return hashItemId;
    }
    return items[0]?.id ?? null;
  }, [hashItemId, items, selectedId]);

  const activeItem = useMemo(
    () => items.find((item) => item.id === selectedItemId) ?? null,
    [items, selectedItemId],
  );

  const heading = scopeLabel(effectiveScope, feeds);
  const pendingLabel = pendingScope
    ? scopeDescription(pendingScope, feeds)
    : "";
  const showingPrevious =
    pendingScope !== null && itemsQuery.isPlaceholderData && items.length > 0;
  const previousHeading = scopeLabel(displayedScope, feeds);
  const hasFilters = Boolean(
    effectiveScope.query ||
      effectiveScope.label ||
      effectiveScope.feedId !== null,
  );

  useEffect(() => {
    if (!pendingScope || !sameScope(scope, pendingScope)) {
      return;
    }
    if (itemsQuery.isPending) {
      return;
    }
    if (itemsQuery.isPlaceholderData && !itemsQuery.error) {
      return;
    }
    completeScopeNavigation();
  }, [
    completeScopeNavigation,
    itemsQuery.error,
    itemsQuery.isPending,
    itemsQuery.isPlaceholderData,
    pendingScope,
    scope,
  ]);

  useEffect(() => {
    if (itemsQuery.isPlaceholderData) {
      return;
    }
    const timer = window.setTimeout(() => {
      setDisplayedScope((current) =>
        sameScope(current, effectiveScope) ? current : effectiveScope,
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [effectiveScope, itemsQuery.isPlaceholderData]);

  useEffect(() => {
    if (openingId === null) {
      return;
    }
    const timer = window.setTimeout(() => setOpeningId(null), 12_000);
    return () => window.clearTimeout(timer);
  }, [openingId]);

  useEffect(() => {
    if (lastScopeKey.current === key) {
      return;
    }
    lastScopeKey.current = key;
    setSelectedId(null);
    setOpeningId(null);
    scrollToTop();
  }, [key, scrollToTop]);

  useEffect(() => {
    if (items.length === 0 || itemsQuery.isPlaceholderData) {
      return;
    }
    if (restoredScope.current === key) {
      return;
    }
    restoredScope.current = key;

    if (hashItemId === null || !items.some((item) => item.id === hashItemId)) {
      return;
    }

    window.requestAnimationFrame(() => {
      document
        .getElementById(`item-${hashItemId}`)
        ?.scrollIntoView({ block: "center" });
    });
  }, [hashItemId, items, itemsQuery.isPlaceholderData, key]);

  const seedItem = useCallback(
    (item: Item) => {
      queryClient.setQueryData<Item>(
        ["item", item.id],
        (current) => current ?? item,
      );
    },
    [queryClient],
  );

  const prepareItemOpen = useCallback(
    (item: Item) => {
      seedItem(item);
      setOpeningId(item.id);
    },
    [seedItem],
  );

  const openItem = useCallback(
    (item: Item) => {
      prepareItemOpen(item);
      router.push(articleHref(item, effectiveScope));
    },
    [effectiveScope, prepareItemOpen, router],
  );

  const retry = useCallback(() => {
    if (pendingScope) {
      navigateToScope(pendingScope);
    }
    void refetchItems();
  }, [navigateToScope, pendingScope, refetchItems]);

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
        return;
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      const key = event.key.toLowerCase();

      if (key === "j" || key === "k") {
        event.preventDefault();
        moveSelection(key === "j" ? 1 : -1);
        return;
      }

      if (!activeItem) {
        return;
      }

      if (key === "o" || event.key === "Enter") {
        event.preventDefault();
        openItem(activeItem);
        return;
      }

      if (key === "v" && activeItem.link) {
        event.preventDefault();
        window.open(activeItem.link, "_blank", "noopener,noreferrer");
        return;
      }

      if (key === "s") {
        event.preventDefault();
        toggleStar(activeItem);
        return;
      }

      if (key === "m") {
        event.preventDefault();
        toggleRead(activeItem);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    activeItem,
    moveSelection,
    openItem,
    shortcutsBlocked,
    toggleRead,
    toggleStar,
  ]);

  return (
    <ArticleList
      items={items}
      total={total}
      loading={loading}
      busy={busy}
      heading={heading}
      pending={pendingScope !== null}
      pendingLabel={pendingLabel}
      pendingSince={pendingSince}
      showingPrevious={showingPrevious}
      previousHeading={previousHeading}
      error={itemsQuery.error}
      onRetry={retry}
      openingId={openingId}
      scope={effectiveScope}
      query={effectiveScope.query}
      view={effectiveScope.view}
      hasFeeds={feeds.length > 0}
      hasFilters={hasFilters}
      feedNames={feedNames}
      feedCounts={feedCounts}
      labels={labels}
      selectedId={selectedItemId}
      onOpen={openItem}
      onOpening={prepareItemOpen}
      onPrefetchItem={seedItem}
      onToggleStar={toggleStar}
      onToggleRead={toggleRead}
      onToggleLabel={toggleLabel}
      onSelectFeed={selectFeed}
      onSelectView={selectView}
      onAddFeed={openAddFeed}
      onClearSearch={clearSearch}
    />
  );
}
