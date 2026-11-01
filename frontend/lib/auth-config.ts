export type AuthMode = "local" | "cloud";

export interface AuthRuntimeConfig {
  mode: AuthMode;
  /** Human-readable setup problem, never a token or a secret. */
  error: string | null;
}

type Env = Record<string, string | undefined>;

function clean(value: string | undefined): string | null {
  const text = value?.trim();
  return text ? text : null;
}

/** Normalize an Auth0 tenant hostname so the SDK receives a bare host. */
export function normalizeAuth0Domain(value: string | undefined): string | null {
  const text = clean(value);
  if (!text) {
    return null;
  }
  return text.replace(/^https?:\/\//i, "").replace(/\/+$/, "");
}

function invalidDomain(domain: string | null): boolean {
  return Boolean(domain && (domain.includes("/") || /\s/.test(domain)));
}

function invalidBaseUrl(value: string | null): boolean {
  if (!value) {
    return true;
  }
  try {
    const url = new URL(value);
    return url.protocol !== "http:" && url.protocol !== "https:";
  } catch {
    return true;
  }
}

/**
 * Read the regular-web-app settings once per request.
 *
 * The Auth0 client secret and session secret stay server-side; only the mode
 * and a setup message cross into the browser bundle.
 */
export function readAuthRuntimeConfig(env: Env): AuthRuntimeConfig {
  const mode: AuthMode = clean(env.DEV_ENV) ? "cloud" : "local";
  if (mode === "local") {
    return { mode, error: null };
  }

  const domain = normalizeAuth0Domain(env.AUTH0_DOMAIN);
  const clientId = clean(env.AUTH0_CLIENT_ID);
  const clientSecret = clean(env.AUTH0_CLIENT_SECRET);
  const sessionSecret = clean(env.AUTH0_SECRET);
  const audience = clean(env.AUTH0_AUDIENCE);
  const appBaseUrl = clean(env.APP_BASE_URL);

  let error: string | null = null;
  if (!domain) {
    error = "Cloud sign-in is not configured. Missing Auth0 domain.";
  } else if (invalidDomain(domain)) {
    error =
      "AUTH0_DOMAIN must be a tenant hostname such as example.us.auth0.com.";
  } else if (!clientId) {
    error = "Cloud sign-in is not configured. Missing Auth0 client ID.";
  } else if (!clientSecret) {
    error = "Cloud sign-in is not configured. Missing Auth0 client secret.";
  } else if (!sessionSecret) {
    error = "Cloud sign-in is not configured. Missing Auth0 session secret.";
  } else if (!audience) {
    error = "Cloud sign-in is not configured. Missing Auth0 audience.";
  } else if (!appBaseUrl) {
    error = "Cloud sign-in is not configured. Missing app base URL.";
  } else if (invalidBaseUrl(appBaseUrl)) {
    error =
      "APP_BASE_URL must be the reader origin, for example http://localhost:3000.";
  }

  return { mode, error };
}
