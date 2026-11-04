"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  notifyApiUnauthorized,
  setApiAccessTokenGetter,
  setApiUnauthorizedHandler,
} from "./api-auth";
import type { AuthMode, AuthRuntimeConfig } from "./auth-config";
import { buildAuthLoginUrl, type AuthLoginOptions } from "./auth-url";
import { resetItemMutations } from "./item-mutations";

export type { AuthLoginOptions } from "./auth-url";

export interface AuthSessionUser {
  name: string | null;
  email: string | null;
  picture: string | null;
}

export interface AuthSession {
  mode: AuthMode;
  user: AuthSessionUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  sessionExpired: boolean;
  authError: string | null;
  configError: string | null;
  login: (options?: AuthLoginOptions) => void;
  logout: () => void;
}

export const AuthSessionContext = createContext<AuthSession | null>(null);

const LOCAL_SESSION: AuthSession = {
  mode: "local",
  user: null,
  isAuthenticated: true,
  isLoading: false,
  sessionExpired: false,
  authError: null,
  configError: null,
  login: () => undefined,
  logout: () => undefined,
};

function configErrorSession(message: string): AuthSession {
  return {
    mode: "cloud",
    user: null,
    isAuthenticated: false,
    isLoading: false,
    sessionExpired: false,
    authError: null,
    configError: message,
    login: () => undefined,
    logout: () => undefined,
  };
}

/** Access the current profile and the sign-in actions for the active mode. */
export function useAuthSession(): AuthSession {
  const session = useContext(AuthSessionContext);
  if (session === null) {
    throw new Error("useAuthSession must be used inside <AuthProvider>.");
  }
  return session;
}

interface Auth0Profile {
  name?: string;
  nickname?: string;
  email?: string;
  picture?: string;
}

function mapProfile(profile: Auth0Profile): AuthSessionUser {
  return {
    name: profile.name?.trim() || profile.nickname?.trim() || null,
    email: profile.email?.trim() || null,
    picture: profile.picture?.trim() || null,
  };
}

async function readProfile(): Promise<Auth0Profile | null> {
  const response = await fetch("/auth/profile", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401 || response.status === 204) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Auth0 profile request failed (${response.status}).`);
  }
  return (await response.json()) as Auth0Profile;
}

async function readAccessToken(): Promise<string | null> {
  const response = await fetch("/auth/access-token", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401) {
    notifyApiUnauthorized();
    return null;
  }
  if (!response.ok) {
    return null;
  }
  const body = (await response.json()) as { token?: unknown };
  return typeof body.token === "string" ? body.token : null;
}

function CloudAuthSession({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthSessionUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    setApiUnauthorizedHandler(() => {
      resetItemMutations();
      setSessionExpired(true);
      queryClient.clear();
    });
    return () => setApiUnauthorizedHandler(null);
  }, [queryClient]);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      try {
        const profile = await readProfile();
        if (cancelled) {
          return;
        }
        setUser(profile ? mapProfile(profile) : null);
        setAuthError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setUser(null);
        setAuthError(
          error instanceof Error
            ? error.message
            : "Could not check your Auth0 session.",
        );
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setApiAccessTokenGetter(readAccessToken);
    return () => setApiAccessTokenGetter(null);
  }, []);

  const login = useCallback((options?: AuthLoginOptions) => {
    setSessionExpired(false);
    const returnTo =
      options?.returnTo ??
      (typeof window === "undefined"
        ? "/feeds"
        : `${window.location.pathname}${window.location.search}`);
    // The auth proxy must see a full document navigation so it can set the
    // session cookie and redirect to Auth0.
    window.location.assign(
      buildAuthLoginUrl(window.location.origin, { ...options, returnTo }),
    );
  }, []);

  const signOut = useCallback(() => {
    setSessionExpired(false);
    resetItemMutations();
    queryClient.clear();
    const returnTo =
      typeof window === "undefined" ? "/" : `${window.location.origin}/`;
    // Logout is a full document navigation through the Auth0 proxy.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(
      `${window.location.origin}/auth/logout?returnTo=${encodeURIComponent(returnTo)}`,
    );
  }, [queryClient]);

  const value = useMemo<AuthSession>(
    () => ({
      mode: "cloud",
      user,
      isAuthenticated: user !== null,
      isLoading,
      sessionExpired,
      authError,
      configError: null,
      login,
      logout: signOut,
    }),
    [authError, isLoading, login, sessionExpired, signOut, user],
  );

  return (
    <AuthSessionContext.Provider value={value}>
      {children}
    </AuthSessionContext.Provider>
  );
}

export function AuthProvider({
  config,
  children,
}: {
  config: AuthRuntimeConfig;
  children: ReactNode;
}) {
  if (config.mode === "local") {
    return (
      <AuthSessionContext.Provider value={LOCAL_SESSION}>
        {children}
      </AuthSessionContext.Provider>
    );
  }

  if (config.error) {
    return (
      <AuthSessionContext.Provider value={configErrorSession(config.error)}>
        {children}
      </AuthSessionContext.Provider>
    );
  }

  return <CloudAuthSession>{children}</CloudAuthSession>;
}
