"use client";

import { Auth0Provider, useAuth0 } from "@auth0/auth0-react";
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
  setApiAccessTokenGetter,
  setApiUnauthorizedHandler,
} from "./api-auth";
import type { AuthMode, AuthRuntimeConfig } from "./auth-config";

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
  login: () => void;
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

function CloudAuthSession({
  children,
}: {
  children: ReactNode;
}) {
  const {
    user,
    isAuthenticated,
    isLoading,
    error,
    getAccessTokenSilently,
    loginWithRedirect,
    logout,
  } = useAuth0();
  const queryClient = useQueryClient();
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    setApiUnauthorizedHandler(() => {
      setSessionExpired(true);
      queryClient.clear();
    });
    return () => setApiUnauthorizedHandler(null);
  }, [queryClient]);

  useEffect(() => {
    if (!isAuthenticated) {
      setApiAccessTokenGetter(null);
      return;
    }

    setApiAccessTokenGetter(async () => {
      return (await getAccessTokenSilently()) ?? null;
    });
    return () => setApiAccessTokenGetter(null);
  }, [getAccessTokenSilently, isAuthenticated]);

  const login = useCallback(() => {
    setSessionExpired(false);
    const returnTo =
      typeof window === "undefined"
        ? "/feeds"
        : `${window.location.pathname}${window.location.search}`;
    void loginWithRedirect({ appState: { returnTo } });
  }, [loginWithRedirect]);

  const signOut = useCallback(() => {
    setSessionExpired(false);
    queryClient.clear();
    void logout({
      logoutParams: {
        returnTo:
          typeof window === "undefined" ? undefined : window.location.origin,
      },
    });
  }, [logout, queryClient]);

  const value = useMemo<AuthSession>(
    () => ({
      mode: "cloud",
      user: user
        ? {
            name: user.name?.trim() || user.nickname?.trim() || null,
            email: user.email?.trim() || null,
            picture: user.picture?.trim() || null,
          }
        : null,
      isAuthenticated,
      isLoading,
      sessionExpired,
      authError: error ? error.message : null,
      configError: null,
      login,
      logout: signOut,
    }),
    [
      error,
      isAuthenticated,
      isLoading,
      login,
      sessionExpired,
      signOut,
      user,
    ],
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

  if (
    config.error ||
    config.domain === null ||
    config.clientId === null ||
    config.audience === null
  ) {
    return (
      <AuthSessionContext.Provider
        value={configErrorSession(
          config.error ?? "Cloud sign-in is not configured.",
        )}
      >
        {children}
      </AuthSessionContext.Provider>
    );
  }

  return (
    <Auth0Provider
      domain={config.domain}
      clientId={config.clientId}
      cacheLocation="memory"
      useRefreshTokens
      useRefreshTokensFallback
      authorizationParams={{
        audience: config.audience,
        scope: "openid profile email",
      }}
    >
      <CloudAuthSession>{children}</CloudAuthSession>
    </Auth0Provider>
  );
}
