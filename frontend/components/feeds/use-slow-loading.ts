"use client";

import { useEffect, useState } from "react";

/**
 * Flip to true only after `active` has stayed true for `delayMs`.
 * Keeps cached navigations from flashing a spinner for a single frame.
 */
export function useDelayedFlag(active: boolean, delayMs: number): boolean {
  const [flagged, setFlagged] = useState(false);

  useEffect(() => {
    if (!active) {
      const reset = window.setTimeout(() => setFlagged(false), 0);
      return () => window.clearTimeout(reset);
    }

    const timer = window.setTimeout(() => setFlagged(true), delayMs);
    return () => window.clearTimeout(timer);
  }, [active, delayMs]);

  return active && flagged;
}

/** Elapsed milliseconds since a timestamp, ticking while it is set. */
export function useElapsedSince(
  startedAt: number | null,
  tickMs = 250,
): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (startedAt === null) {
      return;
    }

    const timer = window.setInterval(() => setNow(Date.now()), tickMs);
    return () => window.clearInterval(timer);
  }, [startedAt, tickMs]);

  return startedAt === null ? 0 : Math.max(0, now - startedAt);
}

export function formatElapsed(ms: number): string {
  const seconds = ms / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}
