import { describe, expect, it } from "vitest";

import {
  contentBlocks,
  contentParagraphs,
  htmlToText,
  plainText,
} from "./text";

describe("htmlToText", () => {
  it("keeps block boundaries without a DOM", () => {
    expect(htmlToText("<p>One</p><p>Two</p>")).toBe("One\n\nTwo");
  });

  it("keeps a line break inside one paragraph", () => {
    expect(htmlToText("<p>One<br>Two</p>")).toBe("One\nTwo");
  });

  it("drops scripts and styles", () => {
    expect(
      htmlToText("<p>Hello</p><script>alert(1)</script><style>p{}</style>"),
    ).toBe("Hello");
  });

  it("decodes entities and numeric references", () => {
    expect(htmlToText("<p>It&#8217;s &amp; more</p>")).toBe("It’s & more");
  });

  it("turns list items into bullet lines", () => {
    expect(htmlToText("<ul><li>One</li><li>Two</li></ul>")).toBe(
      "• One\n• Two",
    );
  });
});

describe("plainText", () => {
  it("collapses block boundaries into one line", () => {
    expect(plainText("<p>One</p><p>Two</p>")).toBe("One Two");
  });
});

describe("contentParagraphs", () => {
  it("splits trafilatura's line-per-block output", () => {
    expect(
      contentParagraphs(
        "A Big Post About Things\nFirst paragraph.\nSecond paragraph.",
      ),
    ).toEqual([
      "A Big Post About Things",
      "First paragraph.",
      "Second paragraph.",
    ]);
  });

  it("keeps consecutive list lines in one block", () => {
    expect(contentParagraphs("- One\n- Two\nAfter")).toEqual([
      "- One\n- Two",
      "After",
    ]);
  });

  it("uses blank lines for HTML and preserves <br> breaks", () => {
    expect(
      contentParagraphs("<p>One<br>Two</p><p>Three</p>"),
    ).toEqual(["One\nTwo", "Three"]);
  });

  it("keeps blank-line paragraphs in plain text", () => {
    expect(contentParagraphs("One\n\nThree")).toEqual(["One", "Three"]);
  });

  it("drops a leading paragraph that repeats the item title", () => {
    expect(
      contentParagraphs(
        "A Big Post About Things\nFirst paragraph.",
        "A Big Post About Things",
      ),
    ).toEqual(["First paragraph."]);
  });

  it("drops a leading HTML heading that repeats the item title", () => {
    expect(
      contentParagraphs(
        "<h2>A Big Post About Things</h2><p>First paragraph.</p>",
        "A Big Post About Things",
      ),
    ).toEqual(["First paragraph."]);
  });

  it("returns no paragraphs for empty content", () => {
    expect(contentParagraphs("  ")).toEqual([]);
  });
});

describe("contentBlocks", () => {
  it("detects a fenced code block between paragraphs", () => {
    expect(
      contentBlocks(
        "Intro paragraph.\n```ts\nconst answer = 42;\nconsole.log(answer);\n```\nOutro paragraph.",
      ),
    ).toEqual([
      { type: "paragraph", text: "Intro paragraph." },
      {
        type: "code",
        text: "const answer = 42;\nconsole.log(answer);",
        language: "ts",
      },
      { type: "paragraph", text: "Outro paragraph." },
    ]);
  });

  it("keeps blank lines inside fenced code", () => {
    expect(
      contentBlocks("Before.\n~~~python\nfirst = 1\n\nsecond = 2\n~~~\nAfter."),
    ).toEqual([
      { type: "paragraph", text: "Before." },
      { type: "code", text: "first = 1\n\nsecond = 2", language: "python" },
      { type: "paragraph", text: "After." },
    ]);
  });

  it("treats an unclosed fence as code to the end", () => {
    expect(contentBlocks("Text.\n```\nunterminated")).toEqual([
      { type: "paragraph", text: "Text." },
      { type: "code", text: "unterminated", language: undefined },
    ]);
  });

  it("leaves HTML content as paragraphs", () => {
    expect(contentBlocks("<p>One</p><pre><code>x = 1</code></pre>")).toEqual([
      { type: "paragraph", text: "One" },
      { type: "paragraph", text: "x = 1" },
    ]);
  });

  it("returns no blocks for empty content", () => {
    expect(contentBlocks("  ")).toEqual([]);
  });
});
