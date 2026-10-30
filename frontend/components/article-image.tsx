"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ImageState = "loading" | "loaded" | "error";

// The reader renders on the server first. Use the layout effect on the client
// so inline images are wrapped before paint, and fall back to useEffect during
// server rendering to avoid React's layout-effect warning.
const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

interface ArticleImageProps {
  src: string;
  alt: string;
  caption?: ReactNode;
  className?: string;
  eager?: boolean;
}

/**
 * A cover image that reserves a quiet block until the file arrives, then
 * reveals it. A failed image is replaced by its alt text instead of a broken
 * icon so the reader still knows what was meant to be there.
 */
export function ArticleImage({
  src,
  alt,
  caption,
  className,
  eager = false,
}: ArticleImageProps) {
  const [state, setState] = useState<ImageState>("loading");
  const imageRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const image = imageRef.current;
    if (!image?.complete) {
      return;
    }

    // A cached image can finish before React attaches onLoad. Check once after
    // paint so the placeholder does not get stuck on a file already in memory.
    const nextState = image.naturalWidth > 0 ? "loaded" : "error";
    const frame = requestAnimationFrame(() => setState(nextState));
    return () => cancelAnimationFrame(frame);
  }, [src]);

  return (
    <figure className={className}>
      <span className="article-image-frame" data-image-state={state}>
        {/* Remote covers come from arbitrary publishers; next/image needs a
            fixed host allowlist, so the sanitized URL is used directly. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={imageRef}
          src={src}
          alt={alt}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={() => setState("loaded")}
          onError={() => setState("error")}
        />
        <span className="article-image-placeholder" aria-hidden="true">
          Loading image…
        </span>
        <span
          className="article-image-fallback"
          role="img"
          aria-label={alt || "Image unavailable"}
        >
          <span className="article-image-fallback-title">Image unavailable</span>
          {alt && (
            <span className="article-image-fallback-alt">{alt}</span>
          )}
        </span>
      </span>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/**
 * Sanitized feed HTML is injected with dangerouslySetInnerHTML, so its images
 * cannot use a React onLoad handler. Wrap each one after render and track its
 * state so the same placeholder and alt fallback apply to inline images.
 */
export function useArticleImages(html: string) {
  const containerRef = useRef<HTMLDivElement>(null);

  useIsomorphicLayoutEffect(() => {
    const container = containerRef.current;
    if (!container || !html) {
      return;
    }

    const cleanups = Array.from(container.querySelectorAll("img")).map(
      enhanceInlineImage,
    );
    return () => cleanups.forEach((cleanup) => cleanup());
  }, [html]);

  return containerRef;
}

function enhanceInlineImage(image: HTMLImageElement): () => void {
  if (image.closest(".article-image-frame")) {
    return () => {};
  }

  const frame = document.createElement("span");
  frame.className = "article-image-frame";
  frame.dataset.imageState = "loading";

  // A small image that shares a paragraph with prose is probably an icon or
  // badge. Reserving a full content-image block for it would cause its own
  // layout jump, so let those collapse while they load.
  const parentElement = image.parentElement;
  if (
    parentElement?.tagName === "P" &&
    Boolean(parentElement.textContent?.trim())
  ) {
    frame.dataset.imageVariant = "inline";
  }

  const placeholder = document.createElement("span");
  placeholder.className = "article-image-placeholder";
  placeholder.setAttribute("aria-hidden", "true");
  placeholder.textContent = "Loading image…";

  const alt = image.alt.trim();
  const title = image.title.trim();
  const detail = alt || title;
  const caption = image
    .closest("figure")
    ?.querySelector("figcaption")
    ?.textContent?.trim();
  const hasContext = Boolean(detail || caption);

  const fallback = document.createElement("span");
  fallback.className = "article-image-fallback";
  fallback.setAttribute("role", "img");
  fallback.setAttribute("aria-label", detail || "Image unavailable");

  const fallbackTitle = document.createElement("span");
  fallbackTitle.className = "article-image-fallback-title";
  fallbackTitle.textContent = "Image unavailable";
  fallback.append(fallbackTitle);

  if (detail) {
    const fallbackAlt = document.createElement("span");
    fallbackAlt.className = "article-image-fallback-alt";
    fallbackAlt.textContent = detail;
    fallback.append(fallbackAlt);
  }

  const parent = image.parentNode;
  if (!parent) {
    return () => {};
  }

  parent.insertBefore(frame, image);
  frame.append(image, placeholder, fallback);

  const markLoaded = () => {
    frame.dataset.imageState = "loaded";
  };
  const markError = () => {
    if (!hasContext) {
      // A decorative image with nothing to describe would only leave an empty
      // card behind, so take it out of the reading flow instead.
      frame.remove();
      return;
    }
    frame.dataset.imageState = "error";
  };

  if (image.complete) {
    if (image.naturalWidth > 0) {
      markLoaded();
    } else {
      markError();
    }
  } else {
    image.addEventListener("load", markLoaded);
    image.addEventListener("error", markError);
  }

  return () => {
    image.removeEventListener("load", markLoaded);
    image.removeEventListener("error", markError);
    if (frame.parentNode) {
      frame.parentNode.insertBefore(image, frame);
      frame.remove();
    }
  };
}
