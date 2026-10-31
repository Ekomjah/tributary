export type AuthMode = "local" | "cloud";

export interface AuthRuntimeConfig {
  mode: AuthMode;
  domain: string | null;
  clientId: string | null;
  audience: string | null;
  /** Human-readable setup problem, never a token or a secret. */
  error: string | null;
}

type Env = Record<string, string | undefined>;

function first(env: Env, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = env[key];
    if (value !== undefined) {
      return value;
    }
  }
  return undefined;
}

function clean(value: string | undefined): string | null {
  const text = value?.trim();
  return text ? text : null;
}

function cleanDomain(value: string | undefined): string | null {
  const text = clean(value);
  if (!text) {
    return null;
  }
  return text.replace(/^https?:\/\//i, "").replace(/\/+$/, "");
}

function invalidDomain(domain: string | null): boolean {
  return Boolean(domain && (domain.includes("/") || /\s/.test(domain)));
}

/**
 * Read the server-only Auth0 settings once per request.
 *
 * Call this after `connection()` in the root layout so a Vercel deployment can
 * change Auth0 or the profile without rebuilding the browser bundle.
 */
export function readAuthRuntimeConfig(env: Env): AuthRuntimeConfig {
  const mode: AuthMode = clean(
    first(env, "DEV_ENV", "TRIBUTARY_DEV_ENV"),
  )
    ? "cloud"
    : "local";
  if (mode === "local") {
    return {
      mode,
      domain: null,
      clientId: null,
      audience: null,
      error: null,
    };
  }

  const domain = cleanDomain(
    first(env, "AUTH0_DOMAIN", "TRIBUTARY_AUTH0_DOMAIN"),
  );
  const clientId = clean(
    first(env, "AUTH0_CLIENT_ID", "TRIBUTARY_AUTH0_CLIENT_ID"),
  );
  const audience = clean(
    first(env, "AUTH0_AUDIENCE", "TRIBUTARY_AUTH0_AUDIENCE"),
  );

  let error: string | null = null;
  if (!domain) {
    error = "Cloud sign-in is not configured. Missing Auth0 domain.";
  } else if (!clientId) {
    error = "Cloud sign-in is not configured. Missing Auth0 client ID.";
  } else if (!audience) {
    error = "Cloud sign-in is not configured. Missing Auth0 audience.";
  } else if (invalidDomain(domain)) {
    error =
      "AUTH0_DOMAIN must be a tenant hostname such as example.us.auth0.com.";
  }

  return {
    mode,
    domain,
    clientId,
    audience,
    error,
  };
}
