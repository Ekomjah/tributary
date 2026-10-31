import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AccountMenu from "./account-menu";
import { AuthSessionContext, type AuthSession } from "@/lib/auth";

function session(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    mode: "cloud",
    user: {
      name: "Ada Lovelace",
      email: "ada@example.com",
      picture: null,
    },
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

function renderMenu(value: AuthSession) {
  return render(
    <AuthSessionContext.Provider value={value}>
      <AccountMenu />
    </AuthSessionContext.Provider>,
  );
}

describe("AccountMenu", () => {
  it("renders nothing in local mode", () => {
    const { container } = renderMenu(
      session({ mode: "local", user: null }),
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while signed out", () => {
    const { container } = renderMenu(
      session({ user: null, isAuthenticated: false }),
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the profile and signs out from the menu", async () => {
    const logout = vi.fn();
    renderMenu(session({ logout }));

    await userEvent.click(
      screen.getByRole("button", { name: /account menu for ada lovelace/i }),
    );

    expect(screen.getByText("ada@example.com")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /sign out/i }));

    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("falls back to the email when the profile has no name", () => {
    renderMenu(
      session({
        user: {
          name: null,
          email: "ada@example.com",
          picture: null,
        },
      }),
    );

    expect(
      screen.getByRole("button", {
        name: /account menu for ada@example.com/i,
      }),
    ).toBeInTheDocument();
  });
});
