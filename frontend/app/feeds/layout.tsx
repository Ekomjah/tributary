import { Suspense } from "react";
import type { Metadata } from "next";
import { Loader2 } from "lucide-react";

import FeedsShell from "@/components/feeds/feeds-shell";
import RequireAuth from "@/components/require-auth";

export const metadata: Metadata = {
  title: "Feeds — Tributary",
};

function FeedsFallback() {
  return (
    <div className="grid h-dvh place-items-center bg-canvas text-muted">
      <div className="flex items-center gap-2 text-[12px]">
        <Loader2
          className="size-3.5 animate-spin motion-reduce:animate-none"
          aria-hidden="true"
        />
        Loading feeds…
      </div>
    </div>
  );
}

export default function FeedsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
      <Suspense fallback={<FeedsFallback />}>
        <FeedsShell>{children}</FeedsShell>
      </Suspense>
    </RequireAuth>
  );
}
