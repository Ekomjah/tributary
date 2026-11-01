import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getApiAccessToken, resetApiAuth } from "./api-auth";
import { AuthProvider, useAuthSession } from "./auth";
import type { AuthRuntimeConfig } from "./auth-config";

function Probe() {
  const auth = useAuthSession();

  if (auth.configError) {
    return <p>config: {auth.configError}</p>;
  }
  if (auth.isLoading) {
    return <p>loading</p>;
  }
  if (auth.mode === "local") {
    return <p>local</p>;
  }
  if (auth.isAuthenticated) {
    return <p>signed in {auth.user?.email}</p>;
  }
  return <p>signed out</p>;
}

function renderProvider(config: AuthRuntimeConfig) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider config={config}>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetApiAuth();
});

describe("AuthProvider", () => {
  it("renders the local session without contacting Auth0", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderProvider({ mode: "local", error: null });

    expect(screen.getByText("local")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads the server-side session and bridges access tokens", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/profile")) {
        return json({ name: "Ada", email: "ada@example.com" });
      }
      if (url.endsWith("/auth/access-token")) {
        return json({ token: "access-token" });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderProvider({ mode: "cloud", error: null });

    expect(await screen.findByText("signed in ada@example.com")).toBeVisible();
    await waitFor(async () => {
      await expect(getApiAccessToken()).resolves.toBe("access-token");
    });
  });

  it("treats a 401 profile as signed out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 401 })),
    );

    renderProvider({ mode: "cloud", error: null });

    expect(await screen.findByText("signed out")).toBeInTheDocument();
  });

  it("reports a broken configuration without fetching", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderProvider({ mode: "cloud", error: "Missing Auth0 domain." });

    expect(
      screen.getByText("config: Missing Auth0 domain."),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
