import Link from "next/link";
import { BookOpen, Workflow } from "lucide-react";

import AccountMenu from "@/components/account-menu";

export default function PipesShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-divider bg-canvas px-4">
        <Link
          href="/"
          className="text-[20px] font-bold leading-none text-danger hover:no-underline hover:opacity-80"
        >
          Tributary
        </Link>
        <span className="text-faint" aria-hidden="true">
          /
        </span>
        <Link
          href="/pipes"
          className="flex items-center gap-1.5 text-[13px] font-bold text-ink hover:no-underline"
        >
          <Workflow className="size-4 text-muted" aria-hidden="true" />
          Pipes
        </Link>
        <Link
          href="/feeds"
          className="ml-auto flex items-center gap-1.5 text-[12px] text-muted hover:text-ink hover:no-underline"
        >
          <BookOpen className="size-3.5" aria-hidden="true" />
          Reader
        </Link>
        <AccountMenu />
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}
