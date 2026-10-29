"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import ArticleList from "@/components/article-list";
import { useFeeds } from "@/components/feeds/feeds-shell";
import { api } from "@/lib/api";
import {
  articleHref,
  itemIdFromHash,
  itemsQueryKey,
  PAGE_SIZE,
  scopeLabel,
} from "@/lib/feeds";
import type { Item } from "@/lib/types";

export default function FeedsList() {
  const router = useRouter();
  const {
    scope,
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
    showError,
    scrollToTop,
  } = useFeeds();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const scopeKey = `${scope.view}|${scope.feedId ?? ""}|${scope.label ?? ""}|${scope.query}`;
  const lastScopeKey = useRef(scopeKey);
  const restoredScope = useRef<string | null>(null);

  const itemsQuery = useQuery({
    queryKey: itemsQueryKey(scope),
    queryFn: ({ signal }) =>
      api.listItems({
        unread: scope.view === "unread" ? true : undefined,
        starred: scope.view === "starred" ? true : undefined,
        feedId: scope.feedId,
        label: scope.label,
        q: scope.query || undefined,
        limit: PAGE_SIZE,
        signal,
      }),
    placeholderData: keepPreviousData,
  });

  const items = useMemo(() => itemsQuery.data?.items ?? [], [itemsQuery.data]);
  const total = itemsQuery.data?.total ?? 0;
  const loading = itemsQuery.isFetching;

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

  const heading = scopeLabel(scope, feeds);
  const hasFilters = Boolean(
    scope.query || scope.label || scope.feedId !== null,
  );

  useEffect(() => {
    if (itemsQuery.error) {
      showError(itemsQuery.error);
    }
  }, [itemsQuery.error, showError]);

  useEffect(() => {
    if (lastScopeKey.current === scopeKey) {
      return;
    }
    lastScopeKey.current = scopeKey;
    setSelectedId(null);
    scrollToTop();
  }, [scopeKey, scrollToTop]);

  useEffect(() => {
    if (items.length === 0 || itemsQuery.isPlaceholderData) {
      return;
    }
    if (restoredScope.current === scopeKey) {
      return;
    }
    restoredScope.current = scopeKey;

    if (hashItemId === null || !items.some((item) => item.id === hashItemId)) {
      return;
    }

    window.requestAnimationFrame(() => {
      document
        .getElementById(`item-${hashItemId}`)
        ?.scrollIntoView({ block: "center" });
    });
  }, [hashItemId, items, itemsQuery.isPlaceholderData, scopeKey]);

  const openItem = useCallback(
    (item: Item) => {
      setSelectedId(item.id);
      router.push(articleHref(item, scope));
    },
    [router, scope],
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
      heading={heading}
      query={scope.query}
      view={scope.view}
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
      onAddFeed={openAddFeed}
      onClearSearch={clearSearch}
    />
  );
}
