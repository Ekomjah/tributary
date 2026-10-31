"use client";

import { Lock, Loader2, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useAuthSession } from "@/lib/auth";

function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas text-ink">
      <header className="border-b border-divider bg-canvas">
        <div className="mx-auto flex h-14 max-w-[1040px] items-center gap-3 px-6 max-[700px]:px-4">
          <span className="text-[20px] font-bold leading-none text-danger">
            Tributary
          </span>
          <span className="border border-line px-1.5 py-0.5 font-mono text-[9px] uppercase leading-none tracking-[0.06em] text-muted">
            Cloud
          </span>
        </div>
      </header>
      <main className="grid flex-1 place-items-center px-6 py-16 max-[700px]:px-4">
        <div className="w-full max-w-[420px]">{children}</div>
      </main>
    </div>
  );
}

function CheckingSession() {
  return (
    <Frame>
      <div
        role="status"
        className="flex items-center justify-center gap-2 text-[12px] text-muted"
      >
        <Loader2
          className="size-3.5 animate-spin motion-reduce:animate-none"
          aria-hidden="true"
        />
        Checking your session…
      </div>
    </Frame>
  );
}

function SignIn() {
  const auth = useAuthSession();
  const configured = auth.configError === null;

  return (
    <Frame>
      <div className="border border-line bg-canvas p-6">
        <p className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
          <Lock className="size-3" aria-hidden="true" />
          Private beta
        </p>
        <h1 className="mt-2 text-[20px] font-bold leading-tight text-ink">
          Sign in to Tributary
        </h1>
        <p className="mt-2 text-[13px] leading-5 text-muted">
          The hosted reader keeps each library behind an Auth0 account. Sign in
          with the account you were invited with to reach your feeds and pipes.
        </p>

        {auth.sessionExpired && configured && (
          <p className="mt-3 border-l-[3px] border-l-warn bg-chrome px-2 py-1.5 text-[12px] leading-5 text-ink">
            Your session expired. Continue with Auth0 to sign in again.
          </p>
        )}

        {auth.configError !== null && (
          <div className="mt-4 border border-line bg-chrome px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-[12px] font-bold text-ink">
              <TriangleAlert className="size-3.5 text-warn" aria-hidden="true" />
              Cloud sign-in is not available
            </p>
            <p className="mt-1 text-[12px] leading-5 text-muted">
              {auth.configError}
            </p>
            <p className="mt-1 font-mono text-[10px] leading-4 text-faint">
              Set DEV_ENV, AUTH0_DOMAIN, AUTH0_CLIENT_ID and AUTH0_AUDIENCE for
              the frontend, then reload.
            </p>
          </div>
        )}

        {auth.authError !== null && configured && (
          <p className="mt-3 text-[11px] leading-4 text-faint">
            The last sign-in attempt did not finish. Try again.
          </p>
        )}

        {configured && (
          <Button
            type="button"
            variant="primary"
            className="mt-5 h-9 w-full"
            onClick={auth.login}
          >
            Continue with Auth0
          </Button>
        )}

        <p className="mt-4 border-t border-divider pt-3 text-[11px] leading-4 text-faint">
          Tributary never receives your Auth0 password. The browser holds the
          access token in memory and sends it to the API as a bearer token.
        </p>
      </div>
    </Frame>
  );
}

/**
 * Gate the reader and pipes routes in cloud mode.
 *
 * Local installations have no account step, so the children render
 * immediately. In cloud mode the app waits for Auth0 to restore a session and
 * then asks the visitor to sign in explicitly; there is no automatic redirect.
 */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuthSession();

  if (auth.mode === "local") {
    return <>{children}</>;
  }

  if (auth.configError !== null || auth.sessionExpired) {
    return <SignIn />;
  }

  if (auth.isLoading) {
    return <CheckingSession />;
  }

  if (!auth.isAuthenticated) {
    return <SignIn />;
  }

  return <>{children}</>;
}
