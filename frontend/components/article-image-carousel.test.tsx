import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ArticleImageCarousel from "./article-image-carousel";
import type { GalleryImage } from "@/lib/article-images";

const IMAGES: GalleryImage[] = [
  { src: "https://example.com/one.jpg", alt: "One", caption: "First caption" },
  { src: "https://example.com/two.jpg", alt: "Two" },
  { src: "https://example.com/three.jpg", alt: "Three" },
];

function Harness({
  images = IMAGES,
  initialIndex = 0,
  onClose,
}: {
  images?: GalleryImage[];
  initialIndex?: number | null;
  onClose?: () => void;
}) {
  const [index, setIndex] = useState<number | null>(initialIndex);

  return (
    <ArticleImageCarousel
      images={images}
      index={index}
      onIndexChange={setIndex}
      onClose={() => {
        onClose?.();
        setIndex(null);
      }}
    />
  );
}

describe("ArticleImageCarousel", () => {
  it("shows the current image, counter, caption and thumbnails", () => {
    render(<Harness />);

    expect(
      screen.getByRole("dialog", { name: /article images/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.getByText("First caption")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "One" })).toHaveAttribute(
      "src",
      IMAGES[0].src,
    );
    expect(
      screen.getByRole("button", { name: /show image 1:/i }),
    ).toHaveAttribute("aria-current", "true");
    expect(
      screen.getByRole("link", { name: /open image/i }),
    ).toHaveAttribute("href", IMAGES[0].src);
  });

  it("moves to the next image with the controls and wraps at the end", async () => {
    render(<Harness initialIndex={2} />);

    await userEvent.click(screen.getByRole("button", { name: /next image/i }));

    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "One" })).toBeInTheDocument();
  });

  it("supports arrow, Home and End keys", () => {
    render(<Harness />);
    const dialog = screen.getByRole("dialog", { name: /article images/i });

    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    expect(screen.getByText("2 / 3")).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "End" });
    expect(screen.getByText("3 / 3")).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "ArrowLeft" });
    expect(screen.getByText("2 / 3")).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Home" });
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("jumps to an image from its thumbnail", async () => {
    render(<Harness />);

    await userEvent.click(
      screen.getByRole("button", { name: /show image 2:/i }),
    );

    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Two" })).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);

    fireEvent.keyDown(
      screen.getByRole("dialog", { name: /article images/i }),
      { key: "Escape" },
    );

    expect(onClose).toHaveBeenCalled();
    expect(
      screen.queryByRole("dialog", { name: /article images/i }),
    ).not.toBeInTheDocument();
  });

  it("hides navigation for a single image", () => {
    render(<Harness images={[IMAGES[0]]} />);

    expect(screen.getByText("1 / 1")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /next image/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show image 1:/i }),
    ).not.toBeInTheDocument();
  });

  it("shows a fallback when the large image fails", () => {
    render(<Harness />);

    fireEvent.error(screen.getByRole("img", { name: "One" }));

    expect(
      screen.getByText(/this image could not be loaded/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open the original file/i }),
    ).toHaveAttribute("href", IMAGES[0].src);
  });
});
