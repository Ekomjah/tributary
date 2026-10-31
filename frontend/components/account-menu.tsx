"use client";

import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAuthSession } from "@/lib/auth";

/** Profile and sign-out control for the hosted profile. */
export default function AccountMenu() {
  const auth = useAuthSession();

  if (
    auth.mode === "local" ||
    auth.configError !== null ||
    !auth.isAuthenticated
  ) {
    return null;
  }

  const name = auth.user?.name || auth.user?.email || "Account";
  const email = auth.user?.email;
  const initial = name.trim().charAt(0).toUpperCase() || "?";

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-1.5 px-1.5 text-[11px] text-muted"
            aria-label={`Account menu for ${name}`}
          />
        }
      >
        {auth.user?.picture ? (
          // Auth0 avatars come from arbitrary identity providers; next/image
          // needs a fixed host allowlist, so the URL is used directly.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={auth.user.picture}
            alt=""
            width={20}
            height={20}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            className="size-5 rounded-full border border-line object-cover"
          />
        ) : (
          <span
            className="grid size-5 place-items-center rounded-full border border-line bg-chrome text-[10px] font-bold text-muted"
            aria-hidden="true"
          >
            {initial}
          </span>
        )}
        <span className="hidden max-w-[120px] truncate sm:inline">{name}</span>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0">
        <div className="border-b border-divider px-3 py-2.5">
          <p className="truncate text-[13px] font-bold text-ink">{name}</p>
          {email && email !== name && (
            <p className="mt-0.5 truncate text-[11px] text-faint">{email}</p>
          )}
        </div>
        <div className="p-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={auth.logout}
          >
            <LogOut className="size-3.5" aria-hidden="true" />
            Sign out
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
