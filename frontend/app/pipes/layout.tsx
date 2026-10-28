import PipesShell from "@/components/pipes/pipes-shell";

export default function PipesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <PipesShell>{children}</PipesShell>;
}
