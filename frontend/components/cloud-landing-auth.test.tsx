import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  CloudBottomActions,
  CloudHeaderAuth,
  CloudHeroActions,
} from "./cloud-landing-auth";
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

function session(overrides: Partial<AuthSession> = {}): AuthSession {
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

function signedOut(login = vi.fn()): AuthSession {
  return session({ user: null, isAuthenticated: false, login });
}

function renderWith(value: AuthSession, ui: ReactNode) {
  return render(
    <AuthSessionContext.Provider value={value}>
      {ui}
    </AuthSessionContext.Provider>,
  );
}

describe("CloudHeaderAuth", () => {
  it("offers sign-in and account creation when signed out", async () => {
    const login = vi.fn();
    renderWith(signedOut(login), <CloudHeaderAuth />);

    await userEvent.click(
      screen.getByRole("button", { name: /^create account$/i }),
    );
    expect(login).toHaveBeenCalledWith({
      screenHint: "signup",
      returnTo: "/feeds",
    });

    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(login).toHaveBeenCalledWith({ returnTo: "/feeds" });
  });

  it("shows the account menu once signed in", () => {
    renderWith(session(), <CloudHeaderAuth />);

    expect(
      screen.getByRole("button", { name: /account menu for ada lovelace/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
  });

  it("shows a checking state instead of flashing auth actions", () => {
    renderWith(
      session({ user: null, isAuthenticated: false, isLoading: true }),
      <CloudHeaderAuth />,
    );

    expect(
      screen.getByRole("status", { name: /checking your session/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
  });

  it("shows nothing when cloud sign-in is misconfigured", () => {
    renderWith(
      session({
        user: null,
        isAuthenticated: false,
        configError: "Missing Auth0 domain.",
      }),
      <CloudHeaderAuth />,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("CloudHeroActions", () => {
  it("offers account creation and sign-in when signed out", async () => {
    const login = vi.fn();
    renderWith(signedOut(login), <CloudHeroActions />);

    await userEvent.click(
      screen.getByRole("button", { name: /^create account$/i }),
    );
    expect(login).toHaveBeenCalledWith({
      screenHint: "signup",
      returnTo: "/feeds",
    });

    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(login).toHaveBeenCalledWith({ returnTo: "/feeds" });
  });

  it("links into the reader when signed in", () => {
    renderWith(session(), <CloudHeroActions />);

    expect(screen.getByRole("link", { name: /open the reader/i })).toHaveAttribute(
      "href",
      "/feeds",
    );
    expect(screen.getByRole("link", { name: /build a pipe/i })).toHaveAttribute(
      "href",
      "/pipes",
    );
    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
  });

  it("waits for the session before choosing a call to action", () => {
    renderWith(
      session({ user: null, isAuthenticated: false, isLoading: true }),
      <CloudHeroActions />,
    );

    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
  });

  it("falls back to reader links when cloud sign-in is misconfigured", () => {
    renderWith(
      session({
        user: null,
        isAuthenticated: false,
        configError: "Missing Auth0 domain.",
      }),
      <CloudHeroActions />,
    );

    expect(screen.getByRole("link", { name: /open the reader/i })).toHaveAttribute(
      "href",
      "/feeds",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("CloudBottomActions", () => {
  it("offers account creation and sign-in when signed out", () => {
    renderWith(signedOut(), <CloudBottomActions />);

    expect(
      screen.getByRole("button", { name: /^create account$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^sign in$/i }),
    ).toBeInTheDocument();
  });

  it("links into the app when signed in", () => {
    renderWith(session(), <CloudBottomActions />);

    expect(screen.getByRole("link", { name: /open the reader/i })).toHaveAttribute(
      "href",
      "/feeds",
    );
    expect(screen.getByRole("link", { name: /open the pipes/i })).toHaveAttribute(
      "href",
      "/pipes",
    );
  });
});
