import {
  AxiosError,
  type AxiosAdapter,
  type InternalAxiosRequestConfig,
} from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, apiHttp } from "./api";
import {
  resetApiAuth,
  setApiAccessTokenGetter,
  setApiUnauthorizedHandler,
} from "./api-auth";

const originalAdapter = apiHttp.defaults.adapter;
let captured: InternalAxiosRequestConfig | null = null;

function respondingAdapter(data: unknown): AxiosAdapter {
  return async (config) => {
    captured = config;
    return {
      data,
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    };
  };
}

function rejectingAdapter(status: number): AxiosAdapter {
  return async (config) => {
    captured = config;
    const response = {
      data: { detail: "Unauthorized" },
      status,
      statusText: "Unauthorized",
      headers: {},
      config,
    };
    throw new AxiosError(
      "Unauthorized",
      AxiosError.ERR_BAD_REQUEST,
      config,
      undefined,
      response,
    );
  };
}

afterEach(() => {
  apiHttp.defaults.adapter = originalAdapter;
  captured = null;
  resetApiAuth();
});

describe("the API client auth interceptors", () => {
  it("sends no Authorization header when no token source is registered", async () => {
    apiHttp.defaults.adapter = respondingAdapter([]);

    await api.listFeeds();

    expect(captured?.headers.get("Authorization")).toBeUndefined();
  });

  it("attaches the bearer token from the registered source", async () => {
    apiHttp.defaults.adapter = respondingAdapter([]);
    setApiAccessTokenGetter(async () => "access-token");

    await api.listFeeds();

    expect(captured?.headers.get("Authorization")).toBe(
      "Bearer access-token",
    );
  });

  it("keeps the request unauthenticated when the token source fails", async () => {
    apiHttp.defaults.adapter = respondingAdapter([]);
    setApiAccessTokenGetter(async () => {
      throw new Error("missing refresh token");
    });

    await api.listFeeds();

    expect(captured?.headers.get("Authorization")).toBeUndefined();
  });

  it("reports a 401 that carried a bearer token", async () => {
    apiHttp.defaults.adapter = rejectingAdapter(401);
    const handler = vi.fn();
    setApiAccessTokenGetter(async () => "access-token");
    setApiUnauthorizedHandler(handler);

    await expect(api.listFeeds()).rejects.toMatchObject({ status: 401 });

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("ignores a 401 that carried no bearer token", async () => {
    apiHttp.defaults.adapter = rejectingAdapter(401);
    const handler = vi.fn();
    setApiUnauthorizedHandler(handler);

    await expect(api.listFeeds()).rejects.toMatchObject({ status: 401 });

    expect(handler).not.toHaveBeenCalled();
  });

  it("ignores other error statuses", async () => {
    apiHttp.defaults.adapter = rejectingAdapter(403);
    const handler = vi.fn();
    setApiAccessTokenGetter(async () => "access-token");
    setApiUnauthorizedHandler(handler);

    await expect(api.listFeeds()).rejects.toMatchObject({ status: 403 });

    expect(handler).not.toHaveBeenCalled();
  });
});
