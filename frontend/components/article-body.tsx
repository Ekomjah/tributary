"use client";

import { useMemo } from "react";
import { Loader2, Sparkles, TriangleAlert } from "lucide-react";

import { ArticleImage, useArticleImages } from "@/components/article-image";
import { hashtagHref, hashtagifyHtml, splitHashtags } from "@/lib/hashtags";
import { contentBlocks } from "@/lib/text";
import type { FetchStatus, Item } from "@/lib/types";

const FAILURE_COPY: Record<Exclude<FetchStatus, "ok">, string> = {
  blocked: "This page is paywalled or blocked automated readers.",
  empty: "The page did not contain readable article text.",
  error: "The page could not be reached.",
};

export function HashtagText({ text }: { text: string }) {
  const parts = useMemo(() => splitHashtags(text), [text]);

  return (
    <>
      {parts.map((part, index) =>
        part.type === "tag" ? (
          <a
            key={`${part.value}-${index}`}
            href={hashtagHref(part.value)}
            className="article-hashtag"
            title={`Search for #${part.value}`}
          >
            #{part.value}
          </a>
        ) : (
          <span key={`text-${index}`}>{part.value}</span>
        ),
      )}
    </>
  );
}

interface ArticleBodyProps {
  item: Item;
  fetching?: boolean;
  className?: string;
}

export default function ArticleBody({
  item,
  fetching = false,
  className,
}: ArticleBodyProps) {
  const text = item.content_full ?? item.content;
  const blocks = useMemo(
    () => contentBlocks(text, item.title),
    [text, item.title],
  );
  // Feed HTML is sanitized with nh3 before storage; never inject it raw.
  // Prefer it whenever present so inline images and formatting survive.
  const showHtml = Boolean(item.content_html);
  const bodyHtml = useMemo(
    () => (item.content_html ? hashtagifyHtml(item.content_html) : ""),
    [item.content_html],
  );
  const fetchFailed =
    item.content_full === null &&
    item.fetch_status !== null &&
    item.fetch_status !== "ok";
  const waitingForText = fetching && item.content_full === null;
  const bodyRef = useArticleImages(bodyHtml);
  const coverImage = item.cover_image;

  return (
    <div className={className}>
      {coverImage && (
        <ArticleImage
          key={coverImage}
          src={coverImage}
          alt={item.cover_image_alt || item.title || "Article cover"}
          className="article-cover"
          eager
          caption={
            item.cover_caption ? (
              <HashtagText text={item.cover_caption} />
            ) : undefined
          }
        />
      )}

      {item.summary && (
        <div className="mt-5 border-l-[3px] border-accent bg-accent-bg px-4 py-3 font-reading text-[15.5px] leading-[1.65] text-ink">
          <span className="font-bold">Summary:</span>{" "}
          <HashtagText text={item.summary} />
        </div>
      )}

      <div className="mt-7">
        {showHtml ? (
          <div
            ref={bodyRef}
            className="article-html"
            dangerouslySetInnerHTML={{ __html: bodyHtml }}
          />
        ) : blocks.length > 0 ? (
          <div className="article-html">
            {blocks.map((block, index) =>
              block.type === "code" ? (
                <pre key={`${item.id}-code-${index}`}>
                  <code data-language={block.language}>{block.text}</code>
                </pre>
              ) : (
                <p key={`${item.id}-${index}`} className="whitespace-pre-line">
                  <HashtagText text={block.text} />
                </p>
              ),
            )}
          </div>
        ) : null}

        {waitingForText && (
          <p
            role="status"
            className="mt-4 flex items-center gap-2 border-t border-divider pt-3 text-[12px] text-muted"
          >
            <Loader2
              className="size-3.5 animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
            Fetching the full text…
          </p>
        )}

        {fetchFailed && (
          <div className="mt-4 border border-line bg-chrome px-4 py-3 text-[13px] leading-5 text-muted">
            <p className="flex items-center gap-1.5 font-bold text-ink">
              <TriangleAlert
                className="size-3.5 shrink-0 text-warn"
                aria-hidden="true"
              />
              Full text unavailable
            </p>
            <p className="mt-1">
              {FAILURE_COPY[item.fetch_status as Exclude<FetchStatus, "ok">]}
              {item.link && (
                <>
                  {" "}
                  <a
                    href={item.link}
                    target="_blank"
                    rel="noreferrer"
                    className="font-bold text-accent hover:underline"
                  >
                    Read it at the source
                  </a>
                  .
                </>
              )}
            </p>
          </div>
        )}

        {blocks.length === 0 &&
          !showHtml &&
          !waitingForText &&
          !fetchFailed && (
            <div className="border border-line bg-chrome px-4 py-3 text-[13px] leading-5 text-muted">
              This feed didn’t send the article body.
              {item.link && (
                <>
                  {" "}
                  <a
                    href={item.link}
                    target="_blank"
                    rel="noreferrer"
                    className="font-bold text-accent hover:underline"
                  >
                    Read it at the source
                  </a>
                  .
                </>
              )}
            </div>
          )}
      </div>

      {item.why_care && (
        <div className="mt-6 border border-line bg-chrome px-4 py-3">
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.06em] text-muted">
            <Sparkles className="size-3.5 text-accent" aria-hidden="true" />
            Why you’d care
          </p>
          <p className="mt-1.5 font-reading text-[14.5px] leading-[1.65] text-ink">
            <HashtagText text={item.why_care} />
          </p>
        </div>
      )}
    </div>
  );
}
