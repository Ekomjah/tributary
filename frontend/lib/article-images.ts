export interface GalleryImage {
  src: string;
  alt: string;
  caption?: string;
}

const GENERIC_ALT = "Article image";

function cleanText(value: string | null | undefined): string {
  return value?.replace(/\s+/g, " ").trim() ?? "";
}

/**
 * Collect the large images the reader is willing to show full size.
 *
 * The cover and body both render through `.article-image-frame`, so reading the
 * DOM after enhancement gives us one ordered list. Inline icons, failed images
 * and duplicate URLs are left out; a broken slide would only waste a click.
 */
export function collectArticleImages(
  root: ParentNode | null | undefined,
): GalleryImage[] {
  if (!root) {
    return [];
  }

  const images: GalleryImage[] = [];
  const seen = new Set<string>();

  for (const frame of root.querySelectorAll<HTMLElement>(
    ".article-image-frame",
  )) {
    if (frame.dataset.imageVariant === "inline") {
      continue;
    }
    if (frame.dataset.imageState === "error") {
      continue;
    }

    const image = frame.querySelector<HTMLImageElement>("img");
    if (!image) {
      continue;
    }

    const src = image.getAttribute("src")?.trim() ?? "";
    if (!src || seen.has(src)) {
      continue;
    }
    seen.add(src);

    const caption = cleanText(
      image.closest("figure")?.querySelector("figcaption")?.textContent,
    );
    const alt =
      cleanText(image.alt) || cleanText(image.title) || caption || GENERIC_ALT;

    images.push(caption ? { src, alt, caption } : { src, alt });
  }

  return images;
}

export function galleryIndexForSrc(
  images: GalleryImage[],
  src: string | null | undefined,
): number {
  if (!src) {
    return -1;
  }
  return images.findIndex((image) => image.src === src);
}

export function sameGallery(a: GalleryImage[], b: GalleryImage[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (image, index) =>
        image.src === b[index]?.src &&
        image.alt === b[index]?.alt &&
        image.caption === b[index]?.caption,
    )
  );
}
