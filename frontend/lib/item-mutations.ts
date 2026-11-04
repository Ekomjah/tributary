import type { QueryClient } from "@tanstack/react-query";

import { api } from "./api";
import {
  applyIntent,
  clearItemOverlay,
  mergeIntents,
  readCachedItem,
  resetItemOverlays,
  setItemOverlay,
  writeItemToCaches,
  type ItemIntent,
} from "./optimistic";
import { withRetry } from "./retry";
import type { Item } from "./types";

/** How long a settled intent stays layered over incoming fetches. */
const OVERLAY_LINGER_MS = 1500;

interface Job {
  /** Last server-confirmed item: the fail-safe we roll back to. */
  base: Item;
  client: QueryClient;
  onFailure?: (failure: ItemMutationFailure) => void;
  inflight?: ItemIntent;
  queued?: ItemIntent;
  lastIntent?: ItemIntent;
  running: boolean;
  done: Promise<void> | null;
  silent: boolean;
}

export interface ItemMutationFailure {
  itemId: number;
  error: unknown;
  retry: () => void;
}

export interface ItemMutationContext {
  queryClient: QueryClient;
  onFailure?: (failure: ItemMutationFailure) => void;
}

/** Bumped on sign-out so responses cannot write into a cleared cache. */
let generation = 0;

const jobs = new Map<number, Job>();
const overlayTimers = new Map<number, ReturnType<typeof setTimeout>>();

/** Drop every optimistic layer; used when the session ends. */
export function resetItemMutations(): void {
  generation += 1;
  jobs.clear();
  for (const timer of overlayTimers.values()) {
    clearTimeout(timer);
  }
  overlayTimers.clear();
  resetItemOverlays();
}

function writeOptimistic(job: Job): void {
  const itemId = job.base.id;
  const intent = mergeIntents(job.inflight, job.queued);
  if (!intent) {
    clearItemOverlay(itemId);
    writeItemToCaches(job.client, itemId, job.base);
    return;
  }

  setItemOverlay(itemId, intent);
  writeItemToCaches(job.client, itemId, applyIntent(job.base, intent));
}

function resync(client: QueryClient, itemId: number): void {
  void client.invalidateQueries({ queryKey: ["item", itemId], exact: true });
  void client.invalidateQueries({ queryKey: ["items"] });
  void client.invalidateQueries({ queryKey: ["counts"] });
}

function rollback(job: Job): void {
  job.inflight = undefined;
  job.queued = undefined;
  job.lastIntent = undefined;
  clearItemOverlay(job.base.id);
  writeItemToCaches(job.client, job.base.id, job.base);
  resync(job.client, job.base.id);
}

function scheduleOverlayClear(itemId: number): void {
  const existing = overlayTimers.get(itemId);
  if (existing) {
    clearTimeout(existing);
  }

  overlayTimers.set(
    itemId,
    setTimeout(() => {
      overlayTimers.delete(itemId);
      if (!jobs.has(itemId)) {
        clearItemOverlay(itemId);
      }
    }, OVERLAY_LINGER_MS),
  );
}

function retryFailed(
  base: Item,
  intent: ItemIntent,
  context: ItemMutationContext,
): void {
  // Fold the retry into any job that started since the banner appeared; its
  // absolute values make merging safe.
  void enqueueItemMutation(base, intent, context);
}

async function drain(job: Job): Promise<void> {
  const itemId = job.base.id;
  const taskGeneration = generation;

  try {
    while (job.inflight) {
      const intent = job.inflight;
      job.lastIntent = intent;

      try {
        const updated = await withRetry(() =>
          api.updateItem(itemId, intent.patch),
        );
        if (taskGeneration !== generation) {
          return;
        }

        job.base = updated;
        job.inflight = job.queued;
        job.queued = undefined;
        writeOptimistic(job);
      } catch (error) {
        if (taskGeneration !== generation) {
          return;
        }

        const context: ItemMutationContext = {
          queryClient: job.client,
          onFailure: job.onFailure,
        };
        const failedBase = job.base;
        // A click that arrived while this attempt was in flight is part of the
        // user's latest desired state, so the retry must carry it too.
        const failedIntent = mergeIntents(intent, job.queued);
        const silent = job.silent;
        rollback(job);
        jobs.delete(itemId);

        if (silent) {
          return;
        }

        job.onFailure?.({
          itemId,
          error,
          retry: () =>
            retryFailed(failedBase, failedIntent ?? intent, context),
        });
        return;
      }
    }

    if (taskGeneration !== generation) {
      return;
    }

    // Keep the settled intent layered for a moment so a GET that was issued
    // before the PATCH cannot land afterwards and undo it.
    if (job.lastIntent) {
      setItemOverlay(itemId, job.lastIntent);
    }
    jobs.delete(itemId);
    scheduleOverlayClear(itemId);
  } finally {
    job.running = false;
  }
}

/**
 * Apply an intent immediately, then persist it with retries. Clicks made while
 * a request is in flight are merged into one follow-up request.
 *
 * The query client is passed per call so a child effect (such as auto
 * mark-as-read) can optimistically update before the shell's own effects run.
 */
export function enqueueItemMutation(
  item: Item,
  intent: ItemIntent,
  context: ItemMutationContext & { silent?: boolean },
): Promise<void> {
  const itemId = item.id;
  const timer = overlayTimers.get(itemId);
  if (timer) {
    clearTimeout(timer);
    overlayTimers.delete(itemId);
  }

  let job = jobs.get(itemId);
  if (!job) {
    job = {
      base: readCachedItem(context.queryClient, itemId) ?? item,
      client: context.queryClient,
      onFailure: context.onFailure,
      inflight: intent,
      running: false,
      done: null,
      silent: context.silent ?? false,
    };
    jobs.set(itemId, job);
  } else if (job.running) {
    job.queued = mergeIntents(job.queued, intent);
    job.silent = job.silent && (context.silent ?? false);
  } else {
    job.inflight = mergeIntents(job.inflight, intent);
    job.silent = job.silent && (context.silent ?? false);
  }

  writeOptimistic(job);

  if (!job.running) {
    job.running = true;
    job.done = drain(job);
  }
  return job.done ?? Promise.resolve();
}
