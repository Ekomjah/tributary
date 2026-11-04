import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import ArticleBody from "./article-body";
import type { Item } from "@/lib/types";

const ITEM: Item = {
  id: 1,
  feed_id: 1,
  guid: "article-1",
  title: "A test article",
  link: null,
  published: null,
  content: "",
  content_html: `
    <p>Some prose.</p>
    <figure>
      <img src="https://example.com/inline.jpg" alt="Inline alt">
      <figcaption>Inline caption</figcaption>
    </figure>
  `,
  author: null,
  cover_image: "https://example.com/cover.jpg",
  cover_image_alt: "Cover alt",
  cover_caption: "Cover caption",
  content_full: null,
  content_fetched_at: null,
  fetch_status: null,
  discussion_url: null,
  points: null,
  comment_count: null,
  shared_by: null,
  shared_at: null,
  origin_feed_title: null,
  source: null,
  is_read: false,
  starred: false,
  decision: null,
  fetched_at: "2024-01-01T00:00:00Z",
  labels: [],
  summary: null,
  why_care: null,
};

const completeDescriptor = Object.getOwnPropertyDescriptor(
  HTMLImageElement.prototype,
  "complete",
);
const widthDescriptor = Object.getOwnPropertyDescriptor(
  HTMLImageElement.prototype,
  "naturalWidth",
);

beforeAll(() => {
  // jsdom never loads the remote files, so make the article images report as
  // loaded instead of falling back to the alt-text card.
  Object.defineProperty(HTMLImageElement.prototype, "complete", {
    configurable: true,
    get: () => true,
  });
  Object.defineProperty(HTMLImageElement.prototype, "naturalWidth", {
    configurable: true,
    get: () => 800,
  });
});

afterAll(() => {
  if (completeDescriptor) {
    Object.defineProperty(
      HTMLImageElement.prototype,
      "complete",
      completeDescriptor,
    );
  }
  if (widthDescriptor) {
    Object.defineProperty(
      HTMLImageElement.prototype,
      "naturalWidth",
      widthDescriptor,
    );
  }
});

describe("ArticleBody image gallery", () => {
  it("reports the cover and inline images and opens the one that was clicked", async () => {
    const onGalleryChange = vi.fn();
    const onOpenGallery = vi.fn();

    render(
      <ArticleBody
        item={ITEM}
        onGalleryChange={onGalleryChange}
        onOpenGallery={onOpenGallery}
      />,
    );

    await waitFor(() => {
      expect(onGalleryChange).toHaveBeenCalled();
    });

    const images = onGalleryChange.mock.calls.at(-1)?.[0] as Array<{
      src: string;
      alt: string;
    }>;
    expect(images.map((image) => image.src)).toEqual([
      "https://example.com/cover.jpg",
      "https://example.com/inline.jpg",
    ]);

    await userEvent.click(
      await screen.findByRole("button", { name: /view image: cover alt/i }),
    );
    expect(onOpenGallery).toHaveBeenLastCalledWith(0);

    await userEvent.click(
      await screen.findByRole("button", {
        name: /view image: inline alt/i,
      }),
    );
    expect(onOpenGallery).toHaveBeenLastCalledWith(1);
  });

  it("activates an inline image from the keyboard", async () => {
    const onOpenGallery = vi.fn();

    render(<ArticleBody item={ITEM} onOpenGallery={onOpenGallery} />);

    const trigger = await screen.findByRole("button", {
      name: /view image: inline alt/i,
    });
    trigger.focus();
    await userEvent.keyboard("{Enter}");

    expect(onOpenGallery).toHaveBeenCalledWith(1);
  });
});
