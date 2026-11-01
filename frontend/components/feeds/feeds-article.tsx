"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, TriangleAlert } from "lucide-react";

import ArticleView from "@/components/article-view";
import { useFeeds } from "@/components/feeds/feeds-shell";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import {
  articleHref,
  feedsHref,
  itemHash,
  itemIdFromSlug,
  itemsQueryOptions,
  scopeLabel,
} from "@/lib/feeds";
import type { Item } from "@/lib/types";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Could not load this article.";
}

function ArticleNotFound({
  backHref,
  message,
  onBackIntent,
}: {
  backHref: string;
  message: string;
  onBackIntent: () => void;
}) {
  return (
    <div className="mx-auto mt-16 max-w-md border border-line bg-sidebar px-6 py-8 text-center">
      <TriangleAlert className="mx-auto size-7 text-warn" aria-hidden="true" />
      <h1 className="mt-3 text-[15px] font-bold">Article not found</h1>
      <p className="mt-1 text-[13px] leading-5 text-muted">{message}</p>
      <Button
        render={
          <Link href={backHref} scroll={false} onNavigate={onBackIntent} />
        }
        variant="secondary"
        size="sm"
        className="mt-4"
      >
        Back to the list
      </Button>
    </div>
  );
}

function ArticleLoadError({
  backHref,
  message,
  onRetry,
  onBackIntent,
}: {
  backHref: string;
  message: string;
  onRetry: () => void;
  onBackIntent: () => void;
}) {
  return (
    <div
      role="alert"
      className="mx-auto mt-16 max-w-md border border-line bg-sidebar px-6 py-8 text-center"
    >
      <TriangleAlert className="mx-auto size-7 text-danger" aria-hidden="true" />
      <h1 className="mt-3 text-[15px] font-bold">
        Could not load this article
      </h1>
      <p className="mt-1 text-[13px] leading-5 text-muted">{message}</p>
      <div className="mt-4 flex items-center justify-center gap-2">
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
        <Button
          render={
            <Link href={backHref} scroll={false} onNavigate={onBackIntent} />
          }
          variant="ghost"
          size="sm"
        >
          Back to the list
        </Button>
      </div>
    </div>
  );
}

export default function FeedsArticle({ slug }: { slug: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const {
    scope,
    beginScopeNavigation,
    feeds,
    labels,
    feedNames,
    feedCounts,
    patchItem,
    fetchArticle,
    fetchingIds,
    toggleStar,
    toggleRead,
    toggleDecision,
    toggleLabel,
    selectFeed,
    shortcutsBlocked,
    showError,
    scrollToTop,
  } = useFeeds();

  const itemId = itemIdFromSlug(slug);
  const ensured = useRef<Set<number>>(new Set());
  const [pendingArticle, setPendingArticle] = useState<{
    id: number;
    title: string;
  } | null>(null);
  const pendingTitle =
    pendingArticle && pendingArticle.id !== itemId
      ? pendingArticle.title
      : null;

  const itemQuery = useQuery({
    queryKey: ["item", itemId],
    enabled: itemId !== null,
    queryFn: ({ signal }) => api.getItem(itemId as number, signal),
    staleTime: 0,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) {
        return false;
      }
      return failureCount < 2;
    },
  });

  const listQuery = useQuery({
    ...itemsQueryOptions(scope),
    enabled: itemId !== null,
  });

  const item = itemQuery.data ?? null;
  const items = useMemo(() => listQuery.data?.items ?? [], [listQuery.data]);
  const contextLabel = scopeLabel(scope, feeds);
  const backHref =
    itemId === null ? feedsHref(scope) : `${feedsHref(scope)}${itemHash(itemId)}`;

  const goBack = useCallback(() => {
    beginScopeNavigation(scope);
    router.push(backHref, { scroll: false });
  }, [backHref, beginScopeNavigation, router, scope]);

  useEffect(() => {
    if (pendingArticle === null) {
      return;
    }
    const timer = window.setTimeout(() => setPendingArticle(null), 12_000);
    return () => window.clearTimeout(timer);
  }, [pendingArticle]);

  useEffect(() => {
    if (listQuery.error) {
      showError(listQuery.error);
    }
  }, [listQuery.error, showError]);

  useEffect(() => {
    scrollToTop();
  }, [itemId, scrollToTop]);

  useEffect(() => {
    if (!item || ensured.current.has(item.id)) {
      return;
    }
    ensured.current.add(item.id);

    if (!item.is_read) {
      patchItem(item, { is_read: true });
    }
    if (
      !item.content_full &&
      item.fetch_status === null &&
      !fetchingIds.has(item.id)
    ) {
      fetchArticle(item.id);
    }
  }, [fetchArticle, fetchingIds, item, patchItem]);

  const navigateArticle = useCallback(
    (step: number) => {
      if (!item || items.length === 0) {
        return;
      }

      const currentIndex = items.findIndex((entry) => entry.id === item.id);
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

      const next = items[nextIndex];
      queryClient.setQueryData<Item>(
        ["item", next.id],
        (current) => current ?? next,
      );
      setPendingArticle({ id: next.id, title: next.title || "Untitled" });
      router.push(articleHref(next, scope));
    },
    [item, items, queryClient, router, scope, setPendingArticle],
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
        if (event.key === "Escape") {
          target.blur();
        }
        return;
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        goBack();
        return;
      }

      const key = event.key.toLowerCase();
      if (key === "j" || key === "k") {
        event.preventDefault();
        navigateArticle(key === "j" ? 1 : -1);
        return;
      }

      if (!item) {
        return;
      }

      if (key === "v" && item.link) {
        event.preventDefault();
        window.open(item.link, "_blank", "noopener,noreferrer");
        return;
      }

      if (key === "s") {
        event.preventDefault();
        toggleStar(item);
        return;
      }

      if (key === "m") {
        event.preventDefault();
        toggleRead(item);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    goBack,
    item,
    navigateArticle,
    shortcutsBlocked,
    toggleRead,
    toggleStar,
  ]);

  if (itemId === null) {
    return (
      <ArticleNotFound
        backHref={backHref}
        message="The address does not point at an article in this reader."
      />
    );
  }

  if (itemQuery.isPending) {
    return (
      <div className="mx-auto w-full max-w-[780px] px-6 py-5 max-[700px]:px-4">
        <div className="flex items-center justify-between gap-3 border-b border-divider pb-2">
          <Link
            href={backHref}
            className="text-[12px] text-accent hover:underline"
          >
            ← Back to {contextLabel}
          </Link>
        </div>
        <div className="mt-6 flex items-center gap-2 text-[12px] text-muted">
          <Loader2
            className="size-3.5 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
          Loading article…
        </div>
      </div>
    );
  }

  if (!item) {
    if (itemQuery.error instanceof ApiError && itemQuery.error.status === 404) {
      return (
        <ArticleNotFound
          backHref={backHref}
          message="This article is no longer in the reader."
        />
      );
    }

    return (
      <ArticleLoadError
        backHref={backHref}
        message={
          itemQuery.error
            ? errorMessage(itemQuery.error)
            : "The address does not point at an article in this reader."
        }
        onRetry={() => {
          void itemQuery.refetch();
        }}
      />
    );
  }

  return (
    <ArticleView
      item={item}
      feedName={feedNames.get(item.feed_id) ?? "Unknown feed"}
      feedCount={feedCounts[item.feed_id] ?? 0}
      labels={labels}
      contextLabel={contextLabel}
      fetching={fetchingIds.has(item.id)}
      pendingTitle={pendingTitle}
      focusItemId={pendingArticle?.id ?? null}
      onBack={goBack}
      onToggleStar={toggleStar}
      onToggleRead={toggleRead}
      onToggleDecision={toggleDecision}
      onToggleLabel={toggleLabel}
      onSelectFeed={selectFeed}
    />
  );
}
