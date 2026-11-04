import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { isRetryableError, retryDelay, withRetry } from "./retry";

describe("isRetryableError", () => {
  it("retries network, rate-limit and server failures", () => {
    expect(isRetryableError(new ApiError("offline", 0))).toBe(true);
    expect(isRetryableError(new ApiError("timeout", 408))).toBe(true);
    expect(isRetryableError(new ApiError("slow down", 429))).toBe(true);
    expect(isRetryableError(new ApiError("boom", 500))).toBe(true);
  });

  it("does not retry client mistakes or cancellations", () => {
    expect(isRetryableError(new ApiError("bad", 400))).toBe(false);
    expect(isRetryableError(new ApiError("expired", 401))).toBe(false);
    expect(isRetryableError(new ApiError("gone", 404))).toBe(false);
    expect(isRetryableError(new ApiError("conflict", 409))).toBe(false);

    const cancelled = new Error("cancelled");
    cancelled.name = "CanceledError";
    expect(isRetryableError(cancelled)).toBe(false);
  });
});

describe("retryDelay", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("doubles the delay and caps it", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(retryDelay(0, 400, 4000)).toBe(400);
    expect(retryDelay(2, 400, 4000)).toBe(1600);
    expect(retryDelay(6, 400, 4000)).toBe(4000);
  });

  it("adds up to a quarter of jitter", () => {
    vi.spyOn(Math, "random").mockReturnValue(1);
    expect(retryDelay(0, 400, 4000)).toBe(500);
    expect(retryDelay(6, 400, 4000)).toBe(5000);
  });
});

describe("withRetry", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("returns the first successful result without waiting", async () => {
    const run = vi.fn().mockResolvedValue("ok");
    await expect(withRetry(run)).resolves.toBe("ok");
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("retries a transient failure and then succeeds", async () => {
    const run = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("offline", 0))
      .mockResolvedValueOnce("ok");

    const assertion = expect(
      withRetry(run, { baseDelay: 100 }),
    ).resolves.toBe("ok");
    await vi.runAllTimersAsync();
    await assertion;
    expect(run).toHaveBeenCalledTimes(2);
  });

  it("stops immediately when the error is not retryable", async () => {
    const run = vi.fn().mockRejectedValue(new ApiError("conflict", 409));

    await expect(withRetry(run)).rejects.toBeInstanceOf(ApiError);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("gives up after the attempt budget", async () => {
    const run = vi.fn().mockRejectedValue(new ApiError("offline", 0));

    const assertion = expect(
      withRetry(run, { attempts: 3, baseDelay: 10 }),
    ).rejects.toBeInstanceOf(ApiError);
    await vi.runAllTimersAsync();
    await assertion;
    expect(run).toHaveBeenCalledTimes(3);
  });
});
