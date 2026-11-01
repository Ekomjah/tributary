import { describe, expect, it } from "vitest";

import { buildAuthLoginUrl } from "./auth-url";

const ORIGIN = "https://tributaries.tech";

describe("buildAuthLoginUrl", () => {
  it("resumes at the reader by default", () => {
    expect(buildAuthLoginUrl(ORIGIN)).toBe(
      `${ORIGIN}/auth/login?returnTo=%2Ffeeds`,
    );
  });

  it("asks Auth0 for the sign-up screen", () => {
    expect(buildAuthLoginUrl(ORIGIN, { screenHint: "signup" })).toBe(
      `${ORIGIN}/auth/login?returnTo=%2Ffeeds&screen_hint=signup`,
    );
  });

  it("keeps a return path with a query string encoded", () => {
    expect(
      buildAuthLoginUrl("http://localhost:3000", {
        returnTo: "/pipes?tab=1",
        screenHint: "signup",
      }),
    ).toBe(
      "http://localhost:3000/auth/login?returnTo=%2Fpipes%3Ftab%3D1&screen_hint=signup",
    );
  });
});
