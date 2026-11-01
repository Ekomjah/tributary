import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Home from "./page";
import {
  AuthSessionContext,
  type AuthSession,
  type AuthSessionUser,
} from "@/lib/auth";

const USER: AuthSessionUser = {
  name: "Ada Lovelace",
  email: "ada@example.com",
  picture: null,
};

function localSession(): AuthSession {
  return {
    mode: "local",
    user: null,
    isAuthenticated: true,
    isLoading: false,
    sessionExpired: false,
    authError: null,
    configError: null,
    login: vi.fn(),
    logout: vi.fn(),
  };
}

function cloudSession(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    mode: "cloud",
    user: USER,
    isAuthenticated: true,
    isLoading: false,
    sessionExpired: false,
    authError: null,
    configError: null,
    login: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  };
}

function renderPage(value: AuthSession) {
  return render(
    <AuthSessionContext.Provider value={value}>
      <Home />
    </AuthSessionContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("landing page", () => {
  it("keeps the self-hosted page free of auth actions", () => {
    vi.stubEnv("DEV_ENV", "");
    renderPage(localSession());

    expect(screen.getByText("Self-hosted · local-first")).toBeInTheDocument();
    expect(
      screen.getByText("No account. No cloud. One SQLite file."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Runs locally. No account, no algorithm."),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /open the reader/i }),
    ).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^sign in$/i }),
    ).not.toBeInTheDocument();
  });

  it("offers sign-up and sign-in throughout the cloud page", () => {
    vi.stubEnv("DEV_ENV", "1");
    renderPage(
      cloudSession({ user: null, isAuthenticated: false }),
    );

    expect(screen.getByText("Hosted · no algorithm")).toBeInTheDocument();
    expect(
      screen.queryByText("No account. No cloud. One SQLite file."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Runs locally. No account, no algorithm."),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /^create account$/i }),
    ).toHaveLength(3);
    expect(
      screen.getAllByRole("button", { name: /^sign in$/i }),
    ).toHaveLength(3);
    expect(
      screen.queryAllByRole("link", { name: /open the reader/i }),
    ).toHaveLength(0);
  });

  it("shows the reader and account menu after cloud sign-in", () => {
    vi.stubEnv("DEV_ENV", "1");
    renderPage(cloudSession());

    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^sign in$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /open the reader/i }),
    ).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /account menu for ada lovelace/i }),
    ).toBeInTheDocument();
  });

  it("does not flash a call to action while the session loads", () => {
    vi.stubEnv("DEV_ENV", "1");
    renderPage(
      cloudSession({ user: null, isAuthenticated: false, isLoading: true }),
    );

    expect(screen.getAllByRole("status")).toHaveLength(3);
    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps reader links when cloud sign-in is misconfigured", () => {
    vi.stubEnv("DEV_ENV", "1");
    renderPage(
      cloudSession({
        user: null,
        isAuthenticated: false,
        configError: "Missing Auth0 domain.",
      }),
    );

    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^sign in$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /open the reader/i }),
    ).toHaveLength(2);
  });
});
