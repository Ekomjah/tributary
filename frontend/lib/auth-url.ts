export type AuthScreenHint = "signup";

export interface AuthLoginOptions {
  /** Ask Auth0 to open the sign-up screen instead of the sign-in screen. */
  screenHint?: AuthScreenHint;
  /** Relative path to resume after authentication. */
  returnTo?: string;
  /**
   * Ask Auth0 to require fresh credentials instead of reusing an existing
   * session. Defaults to "login" because every caller is an explicit
   * sign-in or sign-up action.
   */
  prompt?: "login";
}

/**
 * Build the full-document navigation that starts the Auth0 login flow.
 *
 * `prompt=login` stops a surviving Auth0 session from silently signing the
 * previous account back in; `screen_hint=signup` then opens the sign-up tab.
 */
export function buildAuthLoginUrl(
  origin: string,
  options: AuthLoginOptions = {},
): string {
  const params = new URLSearchParams({
    returnTo: options.returnTo ?? "/feeds",
  });
  if (options.screenHint) {
    params.set("screen_hint", options.screenHint);
  }
  params.set("prompt", options.prompt ?? "login");
  return `${origin}/auth/login?${params.toString()}`;
}

/**
 * Build the logout navigation.
 *
 * No `returnTo` is passed: the Auth0 SDK then uses APP_BASE_URL for
 * `post_logout_redirect_uri`, which keeps the redirect aligned with the
 * origin registered in Auth0.
 */
export function buildAuthLogoutUrl(origin: string): string {
  return `${origin}/auth/logout`;
}
