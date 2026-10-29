import { describe, expect, it } from "vitest";

import { hashtagifyHtml, splitHashtags } from "./hashtags";

describe("splitHashtags", () => {
  it("splits text and hashtags in order", () => {
    expect(splitHashtags("Read #sqlite and #django.")).toEqual([
      { type: "text", value: "Read " },
      { type: "tag", value: "sqlite" },
      { type: "text", value: " and " },
      { type: "tag", value: "django" },
      { type: "text", value: "." },
    ]);
  });

  it("keeps unicode hashtags", () => {
    expect(splitHashtags("#café and #日本語")).toEqual([
      { type: "tag", value: "café" },
      { type: "text", value: " and " },
      { type: "tag", value: "日本語" },
    ]);
  });

  it("ignores issue numbers, hex colours and C#", () => {
    expect(splitHashtags("C# 12, issue #1, colour #abc")).toEqual([
      { type: "text", value: "C# 12, issue #1, colour #abc" },
    ]);
  });
});

describe("hashtagifyHtml", () => {
  it("turns a hashtag into a chip link", () => {
    const html = hashtagifyHtml("<p>Learning #typescript today.</p>");

    expect(html).toContain('class="article-hashtag"');
    expect(html).toContain('href="/feeds?q=%23typescript"');
    expect(html).toContain(">#typescript</a>");
  });

  it("leaves tag names and attribute values untouched", () => {
    const html = '<p title="#notatag">Hi #tag</p>';

    expect(hashtagifyHtml(html)).toBe(
      '<p title="#notatag">Hi <a class="article-hashtag" href="/feeds?q=%23tag" data-hashtag="tag" title="Search for #tag">#tag</a></p>',
    );
  });

  it("skips anchors, code blocks and scripts", () => {
    const html =
      '<a href="/x">#inlink</a><code>#incode</code><pre><code>#inpre</code></pre><script>#inscript</script>';

    expect(hashtagifyHtml(html)).toBe(html);
  });

  it("keeps formatting inside a skipped element intact", () => {
    const html = '<a href="/x">#one <strong>#two</strong> #three</a>';

    expect(hashtagifyHtml(html)).toBe(html);
  });

  it("ignores URL fragments and entities", () => {
    const html =
      '<p>https://example.com/#anchor &#39; #real</p>';

    const result = hashtagifyHtml(html);
    expect(result).toContain("https://example.com/#anchor");
    expect(result).toContain("&#39;");
    expect(result.match(/article-hashtag/g)).toHaveLength(1);
    expect(result).toContain(">#real</a>");
  });

  it("does not match markdown headings", () => {
    expect(hashtagifyHtml("<p>## Heading</p>")).toBe("<p>## Heading</p>");
  });

  it("returns the input when there is no hash", () => {
    expect(hashtagifyHtml("<p>Plain text.</p>")).toBe("<p>Plain text.</p>");
  });
});
