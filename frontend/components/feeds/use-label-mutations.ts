"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";
import { withRetry } from "@/lib/retry";
import type { Label } from "@/lib/types";

function nameKey(name: string): string {
  return name.trim().toLowerCase();
}

function sortLabels(labels: Label[]): Label[] {
  return [...labels].sort((left, right) => left.name.localeCompare(right.name));
}

let tempSequence = 0;

function nextTempId(): number {
  tempSequence -= 1;
  return tempSequence;
}

export function useLabelMutations(options: {
  onStatus: (message: string) => void;
  onError: (error: unknown, retry: () => void) => void;
}) {
  const queryClient = useQueryClient();
  const { onStatus, onError } = options;

  const updateLabels = useCallback(
    (updater: (labels: Label[]) => Label[]) => {
      queryClient.setQueryData<Label[]>(["labels"], (current) =>
        sortLabels(updater(current ?? [])),
      );
    },
    [queryClient],
  );

  const addPending = useCallback(
    (name: string) => {
      const tempId = nextTempId();
      updateLabels((labels) => [
        ...labels,
        { id: tempId, name, pending: true },
      ]);
      return tempId;
    },
    [updateLabels],
  );

  const removePending = useCallback(
    (tempId: number) => {
      updateLabels((labels) => labels.filter((entry) => entry.id !== tempId));
    },
    [updateLabels],
  );

  const replacePending = useCallback(
    (tempId: number, label: Label) => {
      updateLabels((labels) => {
        const next = labels.map((entry) =>
          entry.id === tempId ? { ...label, pending: false } : entry,
        );
        const seen = new Set<number>();
        return next.filter((entry) => {
          if (seen.has(entry.id)) {
            return false;
          }
          seen.add(entry.id);
          return true;
        });
      });
    },
    [updateLabels],
  );

  const findExisting = useCallback(async (name: string): Promise<Label | null> => {
    const key = nameKey(name);
    const cached = queryClient.getQueryData<Label[]>(["labels"]);
    const fromCache = cached?.find(
      (entry) => !entry.pending && nameKey(entry.name) === key,
    );
    if (fromCache) {
      return fromCache;
    }

    try {
      const labels = await api.listLabels();
      return labels.find((entry) => nameKey(entry.name) === key) ?? null;
    } catch {
      return null;
    }
  }, [queryClient]);

  const createLabel = useCallback(
    (name: string): Promise<string | null> => {
      const trimmed = name.trim();
      if (!trimmed) {
        return Promise.resolve("Enter a label name first.");
      }

      // The dialog closes as soon as this returns; the request, its retries and
      // any rollback all happen in the background.
      const start = (labelName: string) => {
        const tempId = addPending(labelName);

        void (async () => {
          try {
            const created = await withRetry(() => api.createLabel(labelName));
            replacePending(tempId, created);
            onStatus(`Label “${created.name}” added.`);
          } catch (error) {
            if (error instanceof ApiError && error.status === 409) {
              // A retry may have created the label after its first response
              // was lost. Adopt the existing one instead of reporting an error.
              const existing = await findExisting(labelName);
              if (existing) {
                replacePending(tempId, existing);
                onStatus(`Label “${existing.name}” already existed.`);
                return;
              }
            }

            removePending(tempId);
            onError(error, () => start(labelName));
          }
        })();
      };

      start(trimmed);
      return Promise.resolve(null);
    },
    [
      addPending,
      findExisting,
      onError,
      onStatus,
      removePending,
      replacePending,
    ],
  );

  return { createLabel };
}
