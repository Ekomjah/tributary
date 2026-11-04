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

interface Configuration {
  queryClient: QueryClient;
  onFailure?: (failure: ItemMutationFailure) => void;
}

let configuration: Configuration | null = null;
/** Bumped on sign-out so responses cannot write into a cleared cache. */
let generation = 0;

const jobs = new Map<number, Job>();
const overlayTimers = new Map<number, ReturnType<typeof setTimeout>>();

export function configureItemMutations(config: Configuration): () => void {
  configuration = config;
  return () => {
    if (configuration === config) {
      // Keep the query client: a request started by the previous shell may
      // still settle after a remount. Only stop reporting failures.
      configuration = { queryClient: config.queryClient };
    }
  };
}

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
  const config = configuration;
  if (!config) {
    return;
  }

  const itemId = job.base.id;
  const intent = mergeIntents(job.inflight, job.queued);
  if (!intent) {
    clearItemOverlay(itemId);
    writeItemToCaches(config.queryClient, itemId, job.base);
    return;
  }

  setItemOverlay(itemId, intent);
  writeItemToCaches(
    config.queryClient,
    itemId,
    applyIntent(job.base, intent),
  );
}

function resync(itemId: number): void {
  const client = configuration?.queryClient;
  if (!client) {
    return;
  }
  void client.invalidateQueries({ queryKey: ["item", itemId], exact: true });
  void client.invalidateQueries({ queryKey: ["items"] });
  void client.invalidateQueries({ queryKey: ["counts"] });
}

function rollback(job: Job): void {
  const config = configuration;
  if (!config) {
    return;
  }

  job.inflight = undefined;
  job.queued = undefined;
  job.lastIntent = undefined;
  clearItemOverlay(job.base.id);
  writeItemToCaches(config.queryClient, job.base.id, job.base);
  resync(job.base.id);
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

function retryFailed(base: Item, intent: ItemIntent): void {
  if (jobs.has(base.id)) {
    return;
  }
  void enqueueItemMutation(base, intent);
}

async function drain(job: Job, config: Configuration): Promise<void> {
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

        const failedBase = job.base;
        const silent = job.silent;
        rollback(job);
        jobs.delete(itemId);

        if (silent) {
          return;
        }

        config.onFailure?.({
          itemId,
          error,
          retry: () => retryFailed(failedBase, intent),
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
 */
export function enqueueItemMutation(
  item: Item,
  intent: ItemIntent,
  options: { silent?: boolean } = {},
): Promise<void> {
  const config = configuration;
  if (!config) {
    return Promise.resolve();
  }

  const itemId = item.id;
  const timer = overlayTimers.get(itemId);
  if (timer) {
    clearTimeout(timer);
    overlayTimers.delete(itemId);
  }

  let job = jobs.get(itemId);
  if (!job) {
    job = {
      base: readCachedItem(config.queryClient, itemId) ?? item,
      inflight: intent,
      running: false,
      done: null,
      silent: options.silent ?? false,
    };
    jobs.set(itemId, job);
  } else if (job.running) {
    job.queued = mergeIntents(job.queued, intent);
    job.silent = job.silent && (options.silent ?? false);
  } else {
    job.inflight = mergeIntents(job.inflight, intent);
    job.silent = job.silent && (options.silent ?? false);
  }

  writeOptimistic(job);

  if (!job.running) {
    job.running = true;
    job.done = drain(job, config);
  }
  return job.done ?? Promise.resolve();
}
