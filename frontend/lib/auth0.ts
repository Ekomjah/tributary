import { Auth0Client } from "@auth0/nextjs-auth0/server";

import { normalizeAuth0Domain } from "./auth-config";

const domain = normalizeAuth0Domain(process.env.AUTH0_DOMAIN);
const audience = process.env.AUTH0_AUDIENCE?.trim();

/**
 * Server-side Auth0 client for the regular web application.
 *
 * The SDK reads AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET, AUTH0_SECRET and
 * APP_BASE_URL from the environment. The audience is required so the access
 * token can be sent to the Tributary API.
 */
export const auth0 = new Auth0Client({
  ...(domain ? { domain } : {}),
  ...(audience ? { authorizationParameters: { audience } } : {}),
  tokenRefreshBuffer: 60,
});
