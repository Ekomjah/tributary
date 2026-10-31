"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AuthProvider } from "@/lib/auth";
import type { AuthRuntimeConfig } from "@/lib/auth-config";

export default function Providers({
  auth,
  children,
}: {
  auth: AuthRuntimeConfig;
  children: ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider config={auth}>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
