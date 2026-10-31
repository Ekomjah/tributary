export type AccessTokenGetter = () => Promise<string | null>;

let accessTokenGetter: AccessTokenGetter | null = null;
let unauthorizedHandler: (() => void) | null = null;

/** Register the Auth0 bridge used by the shared API client. */
export function setApiAccessTokenGetter(next: AccessTokenGetter | null): void {
  accessTokenGetter = next;
}

/** Register what to do when the API rejects a request that carried a token. */
export function setApiUnauthorizedHandler(next: (() => void) | null): void {
  unauthorizedHandler = next;
}

export async function getApiAccessToken(): Promise<string | null> {
  if (accessTokenGetter === null) {
    return null;
  }
  try {
    return await accessTokenGetter();
  } catch {
    // A failed silent refresh should surface as the API's 401, not as an
    // unhandled promise rejection in the axios interceptor.
    return null;
  }
}

export function notifyApiUnauthorized(): void {
  unauthorizedHandler?.();
}

export function resetApiAuth(): void {
  accessTokenGetter = null;
  unauthorizedHandler = null;
}
