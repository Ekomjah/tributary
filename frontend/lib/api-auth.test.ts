import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getApiAccessToken,
  notifyApiUnauthorized,
  resetApiAuth,
  setApiAccessTokenGetter,
  setApiUnauthorizedHandler,
} from "./api-auth";

afterEach(() => {
  resetApiAuth();
});

describe("the API auth bridge", () => {
  it("returns null when no getter is registered", async () => {
    await expect(getApiAccessToken()).resolves.toBeNull();
  });

  it("returns the token from the registered getter", async () => {
    setApiAccessTokenGetter(async () => "access-token");

    await expect(getApiAccessToken()).resolves.toBe("access-token");
  });

  it("returns null when the getter fails", async () => {
    setApiAccessTokenGetter(async () => {
      throw new Error("missing refresh token");
    });

    await expect(getApiAccessToken()).resolves.toBeNull();
  });

  it("notifies only the registered unauthorized handler", () => {
    const handler = vi.fn();
    setApiUnauthorizedHandler(handler);

    notifyApiUnauthorized();

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("clears both registrations on reset", async () => {
    const handler = vi.fn();
    setApiAccessTokenGetter(async () => "access-token");
    setApiUnauthorizedHandler(handler);

    resetApiAuth();

    await expect(getApiAccessToken()).resolves.toBeNull();
    notifyApiUnauthorized();
    expect(handler).not.toHaveBeenCalled();
  });
});
