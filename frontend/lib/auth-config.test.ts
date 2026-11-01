import { describe, expect, it } from "vitest";

import {
  normalizeAuth0Domain,
  readAuthRuntimeConfig,
} from "./auth-config";

const CLOUD_ENV = {
  DEV_ENV: "production",
  AUTH0_DOMAIN: "tenant.example",
  AUTH0_CLIENT_ID: "regular-web-client-id",
  AUTH0_CLIENT_SECRET: "client-secret",
  AUTH0_SECRET: "f".repeat(64),
  AUTH0_AUDIENCE: "https://api.example.test",
  APP_BASE_URL: "http://localhost:3000",
};

describe("readAuthRuntimeConfig", () => {
  it("stays local when DEV_ENV is unset", () => {
    const config = readAuthRuntimeConfig({
      AUTH0_DOMAIN: "tenant.example",
      AUTH0_CLIENT_ID: "regular-web-client-id",
    });

    expect(config).toEqual({ mode: "local", error: null });
  });

  it("stays local when DEV_ENV is blank", () => {
    expect(readAuthRuntimeConfig({ DEV_ENV: "   " }).mode).toBe("local");
  });

  it("accepts a complete cloud configuration without exposing it", () => {
    const config = readAuthRuntimeConfig({
      ...CLOUD_ENV,
      AUTH0_DOMAIN: "  https://tenant.example/  ",
    });

    expect(config).toEqual({ mode: "cloud", error: null });
  });

  it.each([
    ["AUTH0_DOMAIN", /domain/i],
    ["AUTH0_CLIENT_ID", /client ID/i],
    ["AUTH0_CLIENT_SECRET", /client secret/i],
    ["AUTH0_SECRET", /session secret/i],
    ["AUTH0_AUDIENCE", /audience/i],
    ["APP_BASE_URL", /app base URL/i],
  ])("reports a missing %s", (key, message) => {
    const env = { ...CLOUD_ENV, [key]: "" };

    const config = readAuthRuntimeConfig(env);

    expect(config.mode).toBe("cloud");
    expect(config.error).toMatch(message);
  });

  it("rejects a domain with a path", () => {
    const config = readAuthRuntimeConfig({
      ...CLOUD_ENV,
      AUTH0_DOMAIN: "tenant.example/auth",
    });

    expect(config.error).toMatch(/hostname/i);
  });

  it("rejects a domain with whitespace", () => {
    const config = readAuthRuntimeConfig({
      ...CLOUD_ENV,
      AUTH0_DOMAIN: "tenant example",
    });

    expect(config.error).toMatch(/hostname/i);
  });

  it("rejects a relative app base URL", () => {
    const config = readAuthRuntimeConfig({
      ...CLOUD_ENV,
      APP_BASE_URL: "/feeds",
    });

    expect(config.error).toMatch(/reader origin/i);
  });
});

describe("normalizeAuth0Domain", () => {
  it("strips a scheme and trailing slashes", () => {
    expect(normalizeAuth0Domain("https://tenant.example/")).toBe(
      "tenant.example",
    );
  });

  it("returns null for an empty value", () => {
    expect(normalizeAuth0Domain("   ")).toBeNull();
  });
});
