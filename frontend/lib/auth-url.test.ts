import { describe, expect, it } from "vitest";

import { buildAuthLoginUrl, buildAuthLogoutUrl } from "./auth-url";

const ORIGIN = "https://tributaries.tech";

describe("buildAuthLoginUrl", () => {
  it("resumes at the reader and forces fresh credentials", () => {
    expect(buildAuthLoginUrl(ORIGIN)).toBe(
      `${ORIGIN}/auth/login?returnTo=%2Ffeeds&prompt=login`,
    );
  });

  it("asks Auth0 for the sign-up screen and forces fresh credentials", () => {
    expect(buildAuthLoginUrl(ORIGIN, { screenHint: "signup" })).toBe(
      `${ORIGIN}/auth/login?returnTo=%2Ffeeds&screen_hint=signup&prompt=login`,
    );
  });

  it("keeps a return path with a query string encoded", () => {
    expect(
      buildAuthLoginUrl("http://localhost:3000", {
        returnTo: "/pipes?tab=1",
        screenHint: "signup",
      }),
    ).toBe(
      "http://localhost:3000/auth/login?returnTo=%2Fpipes%3Ftab%3D1&screen_hint=signup&prompt=login",
    );
  });
});

describe("buildAuthLogoutUrl", () => {
  it("uses the proxy route without a return path", () => {
    const url = buildAuthLogoutUrl(ORIGIN);

    expect(url).toBe(`${ORIGIN}/auth/logout`);
    expect(url).not.toContain("returnTo");
  });
});
