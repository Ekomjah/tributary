"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  enqueueItemMutation,
  type ItemMutationFailure,
} from "@/lib/item-mutations";
import { optimisticItem } from "@/lib/optimistic";
import type { Decision, Item, ItemUpdate, Label } from "@/lib/types";

export interface PatchItemOptions {
  /** Roll back quietly instead of surfacing a banner (auto mark-as-read). */
  silent?: boolean;
}

export function useItemMutations(options: {
  onError: (error: unknown, retry: () => void) => void;
}) {
  const queryClient = useQueryClient();
  const { onError } = options;

  const onFailure = useCallback(
    (failure: ItemMutationFailure) => {
      onError(failure.error, failure.retry);
    },
    [onError],
  );

  const patchItem = useCallback(
    (item: Item, patch: ItemUpdate, patchOptions?: PatchItemOptions) => {
      void enqueueItemMutation(
        item,
        { patch },
        {
          queryClient,
          onFailure,
          silent: patchOptions?.silent,
        },
      );
    },
    [onFailure, queryClient],
  );

  const toggleStar = useCallback(
    (item: Item) => {
      const current = optimisticItem(item);
      patchItem(current, { starred: !current.starred });
    },
    [patchItem],
  );

  const toggleRead = useCallback(
    (item: Item) => {
      const current = optimisticItem(item);
      patchItem(current, { is_read: !current.is_read });
    },
    [patchItem],
  );

  const toggleDecision = useCallback(
    (item: Item, decision: Decision) => {
      const current = optimisticItem(item);
      patchItem(current, {
        decision: current.decision === decision ? null : decision,
      });
    },
    [patchItem],
  );

  const toggleLabel = useCallback(
    (item: Item, label: Label) => {
      if (label.pending || label.id < 0) {
        return;
      }

      const current = optimisticItem(item);
      const attached = current.labels.some((entry) => entry.id === label.id);
      const labels = attached
        ? current.labels.filter((entry) => entry.id !== label.id)
        : [...current.labels, label];

      void enqueueItemMutation(
        current,
        {
          patch: { label_ids: labels.map((entry) => entry.id) },
          labels,
        },
        { queryClient, onFailure },
      );
    },
    [onFailure, queryClient],
  );

  return { patchItem, toggleStar, toggleRead, toggleDecision, toggleLabel };
}
