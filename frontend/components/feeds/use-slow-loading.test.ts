import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatElapsed,
  useDelayedFlag,
  useElapsedSince,
} from "./use-slow-loading";

describe("useDelayedFlag", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stays quiet until the delay has passed", () => {
    const { result, rerender } = renderHook(
      ({ active }) => useDelayedFlag(active, 120),
      { initialProps: { active: true } },
    );

    expect(result.current).toBe(false);

    act(() => {
      vi.advanceTimersByTime(119);
    });
    expect(result.current).toBe(false);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe(true);

    rerender({ active: false });
    expect(result.current).toBe(false);
  });
});

describe("useElapsedSince", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ticks while a start time is set", () => {
    const { result } = renderHook(() => useElapsedSince(1_000, 250));

    expect(result.current).toBe(0);

    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(result.current).toBe(250);

    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(result.current).toBe(500);
  });
});

describe("formatElapsed", () => {
  it("keeps one decimal below ten seconds and rounds above", () => {
    expect(formatElapsed(1_234)).toBe("1.2s");
    expect(formatElapsed(9_900)).toBe("9.9s");
    expect(formatElapsed(10_000)).toBe("10s");
    expect(formatElapsed(12_345)).toBe("12s");
  });
});
