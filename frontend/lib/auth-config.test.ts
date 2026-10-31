import { describe, expect, it } from "vitest";

import { readAuthRuntimeConfig } from "./auth-config";

const CLOUD_ENV = {
  DEV_ENV: "production",
  AUTH0_DOMAIN: "tenant.example",
  AUTH0_CLIENT_ID: "spa-client-id",
  AUTH0_AUDIENCE: "https://api.example.test",
};

describe("readAuthRuntimeConfig", () => {
  it("stays local when DEV_ENV is unset", () => {
    const config = readAuthRuntimeConfig({
      AUTH0_DOMAIN: "tenant.example",
      AUTH0_CLIENT_ID: "spa-client-id",
    });

    expect(config).toEqual({
      mode: "local",
      domain: null,
      clientId: null,
      audience: null,
      error: null,
    });
  });

  it("stays local when DEV_ENV is blank", () => {
    expect(readAuthRuntimeConfig({ DEV_ENV: "   " }).mode).toBe("local");
  });

  it("reads the cloud configuration and normalizes the domain", () => {
    const config = readAuthRuntimeConfig({
      ...CLOUD_ENV,
      AUTH0_DOMAIN: "  https://tenant.example/  ",
      AUTH0_AUDIENCE: " https://api.example.test ",
    });

    expect(config).toEqual({
      mode: "cloud",
      domain: "tenant.example",
      clientId: "spa-client-id",
      audience: "https://api.example.test",
      error: null,
    });
  });

  it("accepts the TRIBUTARY_ prefixed aliases", () => {
    const config = readAuthRuntimeConfig({
      TRIBUTARY_DEV_ENV: "production",
      TRIBUTARY_AUTH0_DOMAIN: "tenant.example",
      TRIBUTARY_AUTH0_CLIENT_ID: "spa-client-id",
      TRIBUTARY_AUTH0_AUDIENCE: "https://api.example.test",
    });

    expect(config.mode).toBe("cloud");
    expect(config.error).toBeNull();
    expect(config.domain).toBe("tenant.example");
  });

  it.each([
    ["AUTH0_DOMAIN", /domain/i],
    ["AUTH0_CLIENT_ID", /client ID/i],
    ["AUTH0_AUDIENCE", /audience/i],
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
});
