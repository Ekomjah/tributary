import type { NextConfig } from "next";

// Docker-only switches. Both stay unset on Vercel and Render, so the hosted
// build keeps its current behaviour: default output, absolute API URL, CORS.
const dockerOutput = process.env.NEXT_OUTPUT === "standalone";
const apiProxyTarget = process.env.API_PROXY_TARGET?.trim();

const nextConfig: NextConfig = {
  devIndicators: false,
  ...(dockerOutput ? { output: "standalone" as const } : {}),
  experimental: {
    agentFeedback: true,
    // The self-hosted rewrite is the only proxy in front of the API. Next
    // defaults to roughly 30s, which a cold full-text fetch can exceed; pipe
    // runs already return 202 and poll, so this covers only the synchronous
    // endpoints.
    proxyTimeout: 120_000,
  },
  // Only the image sets API_PROXY_TARGET. Local `pnpm dev` and the hosted
  // deployments keep calling the API directly through NEXT_PUBLIC_API_BASE.
  ...(apiProxyTarget
    ? {
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: `${apiProxyTarget}/api/:path*`,
            },
          ];
        },
      }
    : {}),
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
