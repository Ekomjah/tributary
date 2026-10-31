import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import RequireAuth from "./require-auth";
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

function renderGate(value: AuthSession, children = <p>Reader</p>) {
  return render(
    <AuthSessionContext.Provider value={value}>
      <RequireAuth>{children}</RequireAuth>
    </AuthSessionContext.Provider>,
  );
}

describe("RequireAuth", () => {
  it("renders local installs without an account step", () => {
    renderGate(
      session({
        mode: "local",
        user: null,
        isAuthenticated: true,
          }),
    );

    expect(screen.getByText("Reader")).toBeInTheDocument();
    expect(screen.queryByText(/sign in to tributary/i)).not.toBeInTheDocument();
  });

  it("waits for Auth0 before rendering the app", () => {
    renderGate(
      session({
        user: null,
        isAuthenticated: false,
        isLoading: true,
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      /checking your session/i,
    );
    expect(screen.queryByText("Reader")).not.toBeInTheDocument();
  });

  it("asks the visitor to sign in explicitly", async () => {
    const login = vi.fn();
    renderGate(
      session({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        login,
      }),
    );

    expect(screen.getByText(/sign in to tributary/i)).toBeInTheDocument();
    expect(screen.queryByText("Reader")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /continue with auth0/i }),
    );

    expect(login).toHaveBeenCalledTimes(1);
  });

  it("renders the reader once signed in and the token bridge is ready", () => {
    renderGate(session());

    expect(screen.getByText("Reader")).toBeInTheDocument();
  });

  it("explains a broken cloud configuration instead of offering sign-in", () => {
    renderGate(
      session({
        user: null,
        isAuthenticated: false,
        configError: "Cloud sign-in is not configured. Missing Auth0 domain.",
      }),
    );

    expect(
      screen.getByText(/cloud sign-in is not available/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/missing auth0 domain/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /continue with auth0/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Reader")).not.toBeInTheDocument();
  });

  it("shows an expired session notice", () => {
    renderGate(session({ sessionExpired: true }));

    expect(screen.getByText(/your session expired/i)).toBeInTheDocument();
    expect(screen.queryByText("Reader")).not.toBeInTheDocument();
  });
});
