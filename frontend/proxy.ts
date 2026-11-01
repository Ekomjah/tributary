import { NextResponse, type NextRequest } from "next/server";

import { readAuthRuntimeConfig } from "./lib/auth-config";

/**
 * Mount the Auth0 routes in cloud mode and refresh rolling sessions.
 *
 * Local installs stay account-free, so the proxy never constructs the Auth0
 * client when DEV_ENV is empty or the cloud configuration is incomplete.
 */
export async function proxy(request: NextRequest) {
  const config = readAuthRuntimeConfig(process.env);
  if (config.mode !== "cloud" || config.error !== null) {
    return NextResponse.next();
  }

  const { auth0 } = await import("./lib/auth0");
  return auth0.middleware(request);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
