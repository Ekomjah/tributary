"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Loader2,
  Share2,
  TriangleAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { articleHref } from "@/lib/feeds";
import { formatFullDate } from "@/lib/text";
import type { SharePreview } from "@/lib/types";

function messageOf(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas text-ink">
      <header className="border-b border-divider bg-canvas">
        <div className="mx-auto flex h-14 max-w-[1040px] items-center gap-3 px-6 max-[700px]:px-4">
          <Link
            href="/feeds"
            className="text-[20px] font-bold leading-none text-danger hover:no-underline hover:opacity-80"
          >
            Tributary
          </Link>
          <span className="border border-line px-1.5 py-0.5 font-mono text-[9px] uppercase leading-none tracking-[0.06em] text-muted">
            Shared
          </span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[640px] flex-1 px-6 py-10 max-[700px]:px-4 max-[700px]:py-6">
        {children}
      </main>
    </div>
  );
}

function Notice({
  title,
  children,
  retry,
}: {
  title: string;
  children: React.ReactNode;
  retry?: () => void;
}) {
  return (
    <Frame>
      <div className="border border-line bg-sidebar px-6 py-8">
        <TriangleAlert className="size-6 text-warn" aria-hidden="true" />
        <h1 className="mt-3 text-[18px] font-bold leading-tight">{title}</h1>
        <div className="mt-1 text-[13px] leading-5 text-muted">{children}</div>
        <div className="mt-5 flex items-center gap-2">
          {retry && (
            <Button type="button" variant="secondary" size="sm" onClick={retry}>
              Try again
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            nativeButton={false}
            render={<Link href="/feeds" />}
          >
            <ArrowLeft className="size-3.5" />
            Back to the reader
          </Button>
        </div>
      </div>
    </Frame>
  );
}

function ShareDetails({ share }: { share: SharePreview }) {
  return (
    <article className="border border-line bg-canvas">
      <div className="border-b border-divider bg-chrome px-5 py-2.5">
        <p className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
          <Share2 className="size-3" aria-hidden="true" />
          Shared article
        </p>
      </div>

      <div className="px-5 py-5">
        <h1 className="font-reading text-[25px] font-bold leading-[1.22] text-ink text-balance">
          {share.title || "Untitled"}
        </h1>

        <p className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-faint">
          <span className="font-bold text-muted">
            Shared by {share.shared_by ?? "a Tributary reader"}
          </span>
          {share.origin_feed_title && (
            <>
              <span aria-hidden="true">·</span>
              <span>from {share.origin_feed_title}</span>
            </>
          )}
          <span aria-hidden="true">·</span>
          <time dateTime={share.shared_at}>
            {formatFullDate(share.shared_at)}
          </time>
          {share.author && (
            <>
              <span aria-hidden="true">·</span>
              <span>By {share.author}</span>
            </>
          )}
        </p>

        {share.excerpt && (
          <p className="mt-4 border-t border-divider pt-4 text-[14px] leading-6 text-ink">
            {share.excerpt}
          </p>
        )}

        <div className="mt-5 border-t border-divider pt-4">
          <p className="text-[12px] leading-5 text-muted">
            Claiming adds your own copy to{" "}
            <span className="font-bold text-ink">Shared with me</span>. Your
            read, star and label state stays yours, and the original feed does
            not need to be in your reader.
          </p>
        </div>
      </div>
    </article>
  );
}

export default function SharedClaim({ token }: { token: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const preview = useQuery({
    queryKey: ["share", token],
    queryFn: ({ signal }) => api.getShare(token, signal),
    retry: false,
  });

  const claim = useMutation({
    mutationFn: () => api.claimShare(token),
    onSuccess: ({ item, feed }) => {
      queryClient.setQueryData(["item", item.id], item);
      void queryClient.invalidateQueries({ queryKey: ["feeds"] });
      void queryClient.invalidateQueries({ queryKey: ["items"] });
      void queryClient.invalidateQueries({ queryKey: ["counts"] });
      router.push(
        articleHref(item, {
          view: "all",
          feedId: feed.id,
          label: null,
          query: "",
        }),
      );
    },
  });

  if (preview.isPending) {
    return (
      <Frame>
        <div
          role="status"
          className="flex items-center justify-center gap-2 py-16 text-[12px] text-muted"
        >
          <Loader2
            className="size-4 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
          Opening shared article…
        </div>
      </Frame>
    );
  }

  if (preview.error) {
    const status =
      preview.error instanceof ApiError ? preview.error.status : null;
    const title =
      status === 410
        ? "This shared link has expired"
        : status === 404
          ? "This shared link is not available"
          : "Could not open this shared link";
    return (
      <Notice
        title={title}
        retry={() => {
          void preview.refetch();
        }}
      >
        {status === 410
          ? "Ask the sender for a fresh link. Share links last for 30 days."
          : status === 404
            ? "The link is invalid, or the sender removed it. Ask them to share the article again."
            : messageOf(preview.error)}
      </Notice>
    );
  }

  const share = preview.data;
  if (share.shared_by_me) {
    return (
      <Notice title="This is your own share link">
        Send it to someone else signed in to this Tributary deployment. When
        they claim it, the article appears in their Shared with me inbox.
      </Notice>
    );
  }

  if (share.claimed && !share.claimed_by_me) {
    return (
      <Notice title="This link has already been claimed">
        Share links are single-use. Ask the sender to create a new one if you
        still want the article.
      </Notice>
    );
  }

  return (
    <Frame>
      <ShareDetails share={share} />

      {claim.isError && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-1.5 border border-line bg-chrome px-3 py-2 text-[12px] leading-5 text-danger"
        >
          <TriangleAlert
            className="mt-0.5 size-3.5 shrink-0"
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1">{messageOf(claim.error)}</span>
        </div>
      )}

      <div className="mt-4 flex flex-col items-start gap-2">
        <Button
          type="button"
          variant="primary"
          size="sm"
          className="h-8"
          disabled={claim.isPending}
          onClick={() => claim.mutate()}
        >
          {claim.isPending ? (
            <Loader2
              className="size-3.5 animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
          ) : (
            <Share2 className="size-3.5" aria-hidden="true" />
          )}
          {claim.isPending
            ? "Adding to Shared with me…"
            : share.claimed_by_me
              ? "Open in Shared with me"
              : "Add to Shared with me"}
        </Button>
        <p className="text-[11px] leading-4 text-faint">
          This link expires on{" "}
          {formatFullDate(share.expires_at)} and can be claimed once.
        </p>
      </div>
    </Frame>
  );
}
