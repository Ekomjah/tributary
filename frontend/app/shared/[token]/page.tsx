import type { Metadata } from "next";

import RequireAuth from "@/components/require-auth";
import SharedClaim from "@/components/shared-claim";

export const metadata: Metadata = {
  title: "Shared article — Tributary",
};

export default async function SharedArticlePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return (
    <RequireAuth>
      <SharedClaim token={token} />
    </RequireAuth>
  );
}
