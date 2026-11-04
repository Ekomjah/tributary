import { ApiError } from "./api";

export interface RetryOptions {
  /** Total attempts, including the first one. */
  attempts?: number;
  /** Delay before the second attempt; doubles after that. */
  baseDelay?: number;
  maxDelay?: number;
  shouldRetry?: (error: unknown) => boolean;
}

const RETRYABLE_STATUS = new Set([0, 408, 425, 429]);

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error.name === "CanceledError" || error.name === "AbortError")
  );
}

/** Network failures, rate limits and server errors are worth another try. */
export function isRetryableError(error: unknown): boolean {
  if (isAbortError(error)) {
    return false;
  }
  if (error instanceof ApiError) {
    return RETRYABLE_STATUS.has(error.status) || error.status >= 500;
  }
  // Anything that is not an ApiError never reached the server cleanly.
  return true;
}

export function retryDelay(
  attempt: number,
  baseDelay: number,
  maxDelay: number,
): number {
  const exponential = Math.min(maxDelay, baseDelay * 2 ** attempt);
  const jitter = Math.random() * exponential * 0.25;
  return Math.round(exponential + jitter);
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

/**
 * Run an idempotent request again after a transient failure.
 *
 * Absolute PATCH payloads make the item mutations safe to repeat; label
 * creation handles its own duplicate case before calling this.
 */
export async function withRetry<T>(
  run: () => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const attempts = Math.max(1, options.attempts ?? 3);
  const baseDelay = options.baseDelay ?? 400;
  const maxDelay = options.maxDelay ?? 4000;
  const shouldRetry = options.shouldRetry ?? isRetryableError;

  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await run();
    } catch (error) {
      lastError = error;
      if (attempt === attempts - 1 || !shouldRetry(error)) {
        throw error;
      }
      await sleep(retryDelay(attempt, baseDelay, maxDelay));
    }
  }

  throw lastError;
}
