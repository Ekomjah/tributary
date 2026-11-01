"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import AccountMenu from "@/components/account-menu";
import { Button, buttonVariants } from "@/components/ui/button";
import { useAuthSession } from "@/lib/auth";
import { cn } from "@/lib/utils";

type LandingAuthState = "loading" | "signed-in" | "signed-out" | "unavailable";

function useLandingAuth() {
  const auth = useAuthSession();

  const state: LandingAuthState =
    auth.configError !== null
      ? "unavailable"
      : auth.isLoading
        ? "loading"
        : auth.isAuthenticated
          ? "signed-in"
          : "signed-out";

  return {
    state,
    signIn: () => auth.login({ returnTo: "/feeds" }),
    createAccount: () =>
      auth.login({ screenHint: "signup", returnTo: "/feeds" }),
  };
}

function HeaderCheck() {
  return (
    <span
      role="status"
      aria-label="Checking your session"
      aria-busy="true"
      className="flex items-center gap-2"
    >
      <span
        aria-hidden="true"
        className="h-7 w-12 animate-pulse border border-divider bg-chrome motion-reduce:animate-none"
      />
      <span
        aria-hidden="true"
        className="h-7 w-[104px] animate-pulse border border-divider bg-chrome motion-reduce:animate-none"
      />
    </span>
  );
}

/** Sign-in and sign-up controls in the cloud landing page header. */
export function CloudHeaderAuth() {
  const { state, signIn, createAccount } = useLandingAuth();

  if (state === "loading") {
    return <HeaderCheck />;
  }

  if (state === "signed-in") {
    return <AccountMenu />;
  }

  if (state === "unavailable") {
    return null;
  }

  return (
    <>
      <button
        type="button"
        onClick={signIn}
        className="text-ink hover:text-accent"
      >
        Sign in
      </button>
      <Button
        type="button"
        variant="primary"
        size="sm"
        className="px-2.5 text-[10px]"
        onClick={createAccount}
      >
        Create account
      </Button>
    </>
  );
}

/** Primary landing-page call to action for the hosted reader. */
export function CloudHeroActions() {
  const { state, signIn, createAccount } = useLandingAuth();

  if (state === "loading") {
    return (
      <div
        role="status"
        aria-label="Checking your session"
        aria-busy="true"
        className="mt-6 flex flex-wrap items-center gap-2"
      >
        <span
          aria-hidden="true"
          className="h-9 w-[146px] animate-pulse border border-divider bg-chrome motion-reduce:animate-none"
        />
        <span
          aria-hidden="true"
          className="h-9 w-[92px] animate-pulse border border-divider bg-chrome motion-reduce:animate-none"
        />
      </div>
    );
  }

  if (state === "signed-out") {
    return (
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="primary"
          className="h-9 px-5"
          onClick={createAccount}
        >
          Create account
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="secondary"
          className="h-9 px-4"
          onClick={signIn}
        >
          Sign in
        </Button>
      </div>
    );
  }

  return (
    <div className="mt-6 flex flex-wrap items-center gap-2">
      <Link
        href="/feeds"
        className={cn(
          buttonVariants({ variant: "primary" }),
          "h-9 px-5",
        )}
      >
        Open the reader
        <ArrowRight className="size-3.5" aria-hidden="true" />
      </Link>
      <Link
        href="/pipes"
        className={cn(
          buttonVariants({ variant: "secondary" }),
          "h-9 px-4",
        )}
      >
        Build a pipe
      </Link>
    </div>
  );
}

/** Auth actions in the bottom call to action on the cloud landing page. */
export function CloudBottomActions() {
  const { state, signIn, createAccount } = useLandingAuth();

  if (state === "loading") {
    return (
      <div
        role="status"
        aria-label="Checking your session"
        aria-busy="true"
        className="flex flex-wrap gap-x-6 gap-y-2"
      >
        <span
          aria-hidden="true"
          className="h-4 w-[104px] animate-pulse bg-chrome motion-reduce:animate-none"
        />
        <span
          aria-hidden="true"
          className="h-4 w-16 animate-pulse bg-chrome motion-reduce:animate-none"
        />
      </div>
    );
  }

  if (state === "signed-out") {
    return (
      <>
        <button
          type="button"
          onClick={createAccount}
          className="inline-flex items-center gap-1 text-accent hover:underline"
        >
          Create account
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={signIn}
          className="inline-flex items-center gap-1 text-accent hover:underline"
        >
          Sign in
        </button>
      </>
    );
  }

  return (
    <>
      <Link
        href="/feeds"
        className="inline-flex items-center gap-1 text-accent hover:underline"
      >
        Open the reader
        <ArrowRight className="size-3.5" aria-hidden="true" />
      </Link>
      <Link
        href="/pipes"
        className="inline-flex items-center gap-1 text-accent hover:underline"
      >
        Open the pipes
        <ArrowRight className="size-3.5" aria-hidden="true" />
      </Link>
    </>
  );
}
