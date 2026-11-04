import { describe, expect, it } from "vitest";

import {
  collectArticleImages,
  galleryIndexForSrc,
  sameGallery,
} from "./article-images";

function rootWith(html: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = html;
  return root;
}

describe("collectArticleImages", () => {
  it("collects the cover and body images in reading order", () => {
    const root = rootWith(`
      <figure class="article-cover">
        <span class="article-image-frame" data-image-state="loaded">
          <img src="https://example.com/cover.jpg" alt="Cover alt">
        </span>
        <figcaption>The cover caption</figcaption>
      </figure>
      <div class="article-html">
        <figure>
          <span class="article-image-frame" data-image-state="loaded">
            <img src="https://example.com/one.jpg" alt="One">
          </span>
          <figcaption>First caption</figcaption>
        </figure>
        <span class="article-image-frame" data-image-state="loaded">
          <img src="https://example.com/two.jpg" alt="Two">
        </span>
      </div>
    `);

    expect(collectArticleImages(root)).toEqual([
      {
        src: "https://example.com/cover.jpg",
        alt: "Cover alt",
        caption: "The cover caption",
      },
      {
        src: "https://example.com/one.jpg",
        alt: "One",
        caption: "First caption",
      },
      { src: "https://example.com/two.jpg", alt: "Two" },
    ]);
  });

  it("skips inline icons, failed images and duplicate URLs", () => {
    const root = rootWith(`
      <p>
        <span class="article-image-frame" data-image-state="loaded" data-image-variant="inline">
          <img src="https://example.com/icon.png" alt="Icon">
        </span>
        Some prose.
      </p>
      <span class="article-image-frame" data-image-state="loaded">
        <img src="https://example.com/one.jpg" alt="One">
      </span>
      <span class="article-image-frame" data-image-state="loaded">
        <img src="https://example.com/one.jpg" alt="Duplicate">
      </span>
      <span class="article-image-frame" data-image-state="error">
        <img src="https://example.com/broken.jpg" alt="Broken">
      </span>
    `);

    expect(collectArticleImages(root)).toEqual([
      {
        src: "https://example.com/one.jpg",
        alt: "One",
      },
    ]);
  });

  it("falls back through alt, title, caption and a generic label", () => {
    const root = rootWith(`
      <span class="article-image-frame" data-image-state="loading">
        <img src="https://example.com/title.jpg" title="Title text" alt="">
      </span>
      <figure>
        <span class="article-image-frame" data-image-state="loading">
          <img src="https://example.com/caption.jpg" alt="">
        </span>
        <figcaption>Caption text</figcaption>
      </figure>
      <span class="article-image-frame" data-image-state="loading">
        <img src="https://example.com/plain.jpg" alt="">
      </span>
    `);

    expect(collectArticleImages(root)).toEqual([
      { src: "https://example.com/title.jpg", alt: "Title text" },
      {
        src: "https://example.com/caption.jpg",
        alt: "Caption text",
        caption: "Caption text",
      },
      { src: "https://example.com/plain.jpg", alt: "Article image" },
    ]);
  });

  it("returns an empty list without a root", () => {
    expect(collectArticleImages(null)).toEqual([]);
  });
});

describe("galleryIndexForSrc", () => {
  const images = [
    { src: "https://example.com/one.jpg", alt: "One" },
    { src: "https://example.com/two.jpg", alt: "Two" },
  ];

  it("finds an image by its source", () => {
    expect(galleryIndexForSrc(images, "https://example.com/two.jpg")).toBe(1);
  });

  it("returns -1 for a missing or empty source", () => {
    expect(galleryIndexForSrc(images, "https://example.com/three.jpg")).toBe(-1);
    expect(galleryIndexForSrc(images, null)).toBe(-1);
  });
});

describe("sameGallery", () => {
  it("compares every visible field", () => {
    const one = [{ src: "/one.jpg", alt: "One", caption: "Cap" }];
    expect(sameGallery(one, [...one])).toBe(true);
    expect(sameGallery(one, [{ src: "/one.jpg", alt: "One" }])).toBe(false);
    expect(sameGallery(one, [{ src: "/two.jpg", alt: "One", caption: "Cap" }])).toBe(
      false,
    );
  });
});
