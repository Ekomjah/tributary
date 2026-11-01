export type AuthScreenHint = "signup";

export interface AuthLoginOptions {
  /** Ask Auth0 to open the sign-up screen instead of the sign-in screen. */
  screenHint?: AuthScreenHint;
  /** Relative path to resume after authentication. */
  returnTo?: string;
}

/** Build the full-document navigation that starts the Auth0 login flow. */
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
  return `${origin}/auth/login?${params.toString()}`;
}
