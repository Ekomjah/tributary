"use client";

import { useState, type KeyboardEvent } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  TriangleAlert,
  X,
} from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { GalleryImage } from "@/lib/article-images";
import { cn } from "@/lib/utils";

interface ArticleImageCarouselProps {
  images: GalleryImage[];
  index: number | null;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}

export default function ArticleImageCarousel({
  images,
  index,
  onIndexChange,
  onClose,
}: ArticleImageCarouselProps) {
  const open = index !== null && images.length > 0;
  const currentIndex =
    index === null
      ? 0
      : Math.max(0, Math.min(index, Math.max(0, images.length - 1)));
  const current = images[currentIndex];
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);

  function step(direction: number) {
    if (images.length === 0) {
      return;
    }
    onIndexChange(
      (currentIndex + direction + images.length) % images.length,
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.defaultPrevented) {
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }

    if (images.length < 2) {
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      event.stopPropagation();
      step(-1);
      return;
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      event.stopPropagation();
      step(1);
      return;
    }

    if (event.key === "Home") {
      event.preventDefault();
      event.stopPropagation();
      onIndexChange(0);
      return;
    }

    if (event.key === "End") {
      event.preventDefault();
      event.stopPropagation();
      onIndexChange(images.length - 1);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      <DialogContent
        showCloseButton={false}
        overlayClassName="bg-black/60"
        onKeyDown={handleKeyDown}
        className="flex h-[calc(100dvh-2rem)] max-h-[880px] w-[calc(100%-2rem)] max-w-[1100px] flex-col gap-0 p-0"
      >
        <DialogTitle className="sr-only">Article images</DialogTitle>
        <DialogDescription className="sr-only">
          Use the left and right arrow keys to move between images. Press Escape
          to close the viewer.
        </DialogDescription>

        <header className="flex min-h-12 items-center gap-3 border-b border-divider bg-chrome px-3">
          <span className="text-[11px] font-bold uppercase tracking-[0.06em] text-muted">
            Images
          </span>
          <span
            aria-live="polite"
            className="font-mono text-[11px] text-faint"
          >
            {currentIndex + 1} / {images.length}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            {current && (
              <a
                href={current.src}
                target="_blank"
                rel="noreferrer"
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
              >
                <ExternalLink className="size-3.5" />
                Open image
              </a>
            )}
            <DialogClose className="grid size-7 place-items-center rounded-sm text-muted transition-colors hover:bg-[#e8e8e8] hover:text-ink">
              <X className="size-4" aria-hidden="true" />
              <span className="sr-only">Close image viewer</span>
            </DialogClose>
          </div>
        </header>

        <div className="relative flex min-h-0 flex-1 items-center justify-center bg-sidebar p-3">
          {images.length > 1 && (
            <>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                onClick={() => step(-1)}
                aria-label="Previous image"
                className="absolute left-2 top-1/2 z-10 -translate-y-1/2 shadow-float"
              >
                <ChevronLeft className="size-4" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                onClick={() => step(1)}
                aria-label="Next image"
                className="absolute right-2 top-1/2 z-10 -translate-y-1/2 shadow-float"
              >
                <ChevronRight className="size-4" aria-hidden="true" />
              </Button>
            </>
          )}

          {current && failedSrc !== current.src && (
            <>
              {loadedSrc !== current.src && (
                <span className="absolute font-sans text-[11px] uppercase tracking-[0.04em] text-faint">
                  Loading image…
                </span>
              )}
              {/* Remote article images are arbitrary hosts, so the sanitized
                  URL is used directly. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                key={current.src}
                src={current.src}
                alt={current.alt}
                referrerPolicy="no-referrer"
                onLoad={() => setLoadedSrc(current.src)}
                onError={() => setFailedSrc(current.src)}
                className="relative max-h-full max-w-full object-contain"
              />
            </>
          )}

          {current && failedSrc === current.src && (
            <div className="flex max-w-sm flex-col items-center gap-2 border border-line bg-canvas px-5 py-6 text-center">
              <TriangleAlert
                className="size-5 text-warn"
                aria-hidden="true"
              />
              <p className="text-[13px] font-bold text-ink">
                This image could not be loaded
              </p>
              <p className="font-reading text-[12px] leading-5 text-muted">
                {current.alt}
              </p>
              <a
                href={current.src}
                target="_blank"
                rel="noreferrer"
                className="text-[12px] font-bold text-accent hover:underline"
              >
                Open the original file
              </a>
            </div>
          )}
        </div>

        <footer className="border-t border-divider bg-canvas">
          {current && (current.caption || current.alt) && (
            <p className="px-4 py-2 text-center font-reading text-[13px] leading-5 text-muted">
              {current.caption || current.alt}
            </p>
          )}

          {images.length > 1 && (
            <div
              role="group"
              aria-label="Image thumbnails"
              className="flex gap-1.5 overflow-x-auto border-t border-divider px-3 py-2"
            >
              {images.map((image, imageIndex) => (
                <button
                  key={`${image.src}-${imageIndex}`}
                  type="button"
                  onClick={() => onIndexChange(imageIndex)}
                  aria-label={`Show image ${imageIndex + 1}${
                    image.alt ? `: ${image.alt}` : ""
                  }`}
                  aria-current={
                    imageIndex === currentIndex ? "true" : undefined
                  }
                  className={cn(
                    "size-12 shrink-0 overflow-hidden rounded-sm border bg-chrome transition-colors",
                    imageIndex === currentIndex
                      ? "border-accent ring-1 ring-accent"
                      : "border-line hover:border-muted",
                  )}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={image.src}
                    alt=""
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    className="size-full object-cover"
                  />
                </button>
              ))}
            </div>
          )}
        </footer>
      </DialogContent>
    </Dialog>
  );
}
