import PipesShell from "@/components/pipes/pipes-shell";
import RequireAuth from "@/components/require-auth";

export default function PipesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
      <PipesShell>{children}</PipesShell>
    </RequireAuth>
  );
}
