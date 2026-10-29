import { describe, expect, it } from "vitest";

import {
  defaultStep,
  graphToSteps,
  stepHint,
  stepsToGraph,
  validateStep,
  withArticle,
  type BoxNode,
} from "./pipes";
import type { ArticleFetch, Item, PipeStep } from "./types";

const STEPS: PipeStep[] = [
  { box: "fetch", urls: ["https://hnrss.org/frontpage"] },
  { box: "merge" },
  { box: "dedupe", by: "link" },
  { box: "filter", keyword: "python", fields: ["title", "content"] },
  { box: "sort", by: "published", order: "desc" },
  { box: "limit", count: 5 },
  { box: "fulltext" },
];

function node(id: string, step: PipeStep): BoxNode {
  return {
    id,
    type: "box",
    position: { x: 0, y: 0 },
    data: { step },
  };
}

describe("stepsToGraph", () => {
  it("round-trips a linear pipe", () => {
    const graph = stepsToGraph(STEPS);
    const result = graphToSteps(graph.nodes, graph.edges);

    expect(result).toEqual({
      ok: true,
      steps: STEPS,
      nodeIds: STEPS.map((_, index) => `step-${index}`),
    });
  });

  it("lays nodes out from left to right", () => {
    const graph = stepsToGraph(STEPS);

    expect(graph.nodes.map((entry) => entry.position.x)).toEqual([
      60, 320, 580, 840, 1100, 1360, 1620,
    ]);
    expect(graph.edges).toHaveLength(STEPS.length - 1);
  });

  it("uses saved positions when supplied", () => {
    const graph = stepsToGraph(STEPS.slice(0, 2), {
      "step-0": { x: 12, y: 34 },
    });

    expect(graph.nodes[0].position).toEqual({ x: 12, y: 34 });
    expect(graph.nodes[1].position).toEqual({ x: 320, y: 140 });
  });
});

describe("graphToSteps", () => {
  it("rejects an empty graph", () => {
    const result = graphToSteps([], []);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toMatch(/at least one box/i);
    }
  });

  it("rejects a branch", () => {
    const nodes = [
      node("a", { box: "fetch", urls: ["https://example.com/feed"] }),
      node("b", { box: "limit", count: 5 }),
      node("c", { box: "limit", count: 2 }),
    ];
    const edges = [
      { id: "e1", source: "a", target: "b" },
      { id: "e2", source: "a", target: "c" },
    ];

    const result = graphToSteps(nodes, edges);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toMatch(/single chain/i);
    }
  });

  it("rejects two boxes feeding one box", () => {
    const nodes = [
      node("a", { box: "fetch", urls: ["https://example.com/a"] }),
      node("b", { box: "fetch", urls: ["https://example.com/b"] }),
      node("c", { box: "merge" }),
    ];
    const edges = [
      { id: "e1", source: "a", target: "c" },
      { id: "e2", source: "b", target: "c" },
    ];

    const result = graphToSteps(nodes, edges);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toMatch(/single chain/i);
    }
  });

  it("rejects a loop", () => {
    const nodes = [
      node("a", { box: "fetch", urls: ["https://example.com/a"] }),
      node("b", { box: "limit", count: 5 }),
    ];
    const edges = [
      { id: "e1", source: "a", target: "b" },
      { id: "e2", source: "b", target: "a" },
    ];

    const result = graphToSteps(nodes, edges);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toMatch(/loop/i);
    }
  });

  it("rejects disconnected boxes", () => {
    const nodes = [
      node("a", { box: "fetch", urls: ["https://example.com/a"] }),
      node("b", { box: "limit", count: 5 }),
      node("c", { box: "fulltext" }),
    ];
    const edges = [{ id: "e1", source: "a", target: "b" }];

    const result = graphToSteps(nodes, edges);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toMatch(/not connected/i);
    }
  });

  it("requires a source box first", () => {
    const nodes = [node("a", { box: "limit", count: 5 })];

    const result = graphToSteps(nodes, []);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toMatch(/Fetch or Search/);
    }
  });

  it("reports the invalid node", () => {
    const nodes = [
      node("a", { box: "fetch", urls: ["https://example.com/a"] }),
      node("b", { box: "filter", keyword: "", fields: ["title"] }),
    ];
    const edges = [{ id: "e1", source: "a", target: "b" }];

    const result = graphToSteps(nodes, edges);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.nodeId).toBe("b");
      expect(result.message).toMatch(/keyword/i);
    }
  });
});

describe("validateStep", () => {
  it("validates fetch URLs", () => {
    expect(validateStep({ box: "fetch", urls: [] })).not.toEqual([]);
    expect(validateStep({ box: "fetch", urls: ["not a url"] })).not.toEqual([]);
    expect(
      validateStep({ box: "fetch", urls: ["https://example.com/feed"] }),
    ).toEqual([]);
  });

  it("validates filter fields", () => {
    expect(
      validateStep({ box: "filter", keyword: "python", fields: [] }),
    ).not.toEqual([]);
    expect(
      validateStep({
        box: "filter",
        keyword: "python",
        fields: ["title", "content"],
      }),
    ).toEqual([]);
  });

  it("validates limit bounds", () => {
    expect(validateStep({ box: "limit", count: 0 })).not.toEqual([]);
    expect(validateStep({ box: "limit", count: 501 })).not.toEqual([]);
    expect(validateStep({ box: "limit", count: 10 })).toEqual([]);
  });

  it("validates a meaning criterion", () => {
    expect(validateStep({ box: "meaning", criterion: "" })).not.toEqual([]);
    expect(
      validateStep({ box: "meaning", criterion: "databases, not hype" }),
    ).toEqual([]);
  });

  it("validates search settings", () => {
    expect(
      validateStep({
        box: "search",
        query: "AI regulation this week",
        max_results: 10,
      }),
    ).toEqual([]);
    expect(
      validateStep({ box: "search", query: "", max_results: 10 }),
    ).not.toEqual([]);
    expect(
      validateStep({
        box: "search",
        query: "AI",
        max_results: 50,
      }),
    ).not.toEqual([]);
  });
});

describe("defaultStep", () => {
  it("returns a valid default for every available box", () => {
    const types = [
      "fetch",
      "search",
      "merge",
      "dedupe",
      "filter",
      "sort",
      "limit",
      "fulltext",
      "summarize",
      "meaning",
      "whycare",
    ] as const;

    for (const type of types) {
      const step = defaultStep(type);
      expect(step.box).toBe(type);
    }
  });
});

describe("stepHint", () => {
  it("describes boxes that add items", () => {
    expect(
      stepHint({ box: "fetch", items_in: 0, items_out: 12 }),
    ).toBe("added 12");
  });

  it("describes boxes that drop items", () => {
    expect(
      stepHint({ box: "filter", items_in: 12, items_out: 3 }),
    ).toBe("dropped 9");
  });

  it("flags an empty result", () => {
    expect(stepHint({ box: "fetch", items_in: 0, items_out: 0 })).toBe(
      "no items out",
    );
    expect(
      stepHint({ box: "filter", items_in: 8, items_out: 0 }),
    ).toBe("dropped 8");
  });

  it("flags a source that adds nothing", () => {
    expect(
      stepHint({ box: "search", items_in: 8, items_out: 8 }),
    ).toBe("no new items");
    expect(stepHint({ box: "fetch", items_in: 8, items_out: 8 })).toBe(
      "no new items",
    );
  });

  it("stays quiet for pass-through boxes", () => {
    expect(
      stepHint({ box: "fulltext", items_in: 5, items_out: 5 }),
    ).toBeNull();
    expect(
      stepHint({ box: "summarize", items_in: 5, items_out: 5 }),
    ).toBeNull();
  });
});

describe("withArticle", () => {
  const item: Item = {
    id: 7,
    feed_id: 2,
    guid: "guid-7",
    title: "A useful article",
    link: "https://example.com/a",
    published: null,
    content: "Feed excerpt",
    content_html: null,
    author: "Feed Author",
    cover_image: "https://example.com/feed-cover.jpg",
    cover_image_alt: "Feed cover",
    cover_caption: null,
    content_full: null,
    content_fetched_at: null,
    fetch_status: null,
    source: "Example",
    is_read: false,
    starred: false,
    decision: null,
    fetched_at: "2026-01-01T00:00:00Z",
    labels: [],
    summary: "A short summary.",
    why_care: "It matches your interests.",
  };

  const article: ArticleFetch = {
    id: 7,
    content_html: "<p>Full article</p>",
    author: "Jane Doe",
    cover_image: "https://example.com/article-cover.jpg",
    cover_image_alt: "Article cover",
    cover_caption: "The cover caption.",
    content_full: "Full article",
    content_fetched_at: "2026-01-02T00:00:00Z",
    fetch_status: "ok",
  };

  it("merges the fetched article without losing item state", () => {
    const updated = withArticle(item, article);

    expect(updated.content_full).toBe("Full article");
    expect(updated.content_html).toBe("<p>Full article</p>");
    expect(updated.author).toBe("Jane Doe");
    expect(updated.cover_image).toBe("https://example.com/article-cover.jpg");
    expect(updated.cover_image_alt).toBe("Article cover");
    expect(updated.cover_caption).toBe("The cover caption.");
    expect(updated.fetch_status).toBe("ok");
    expect(updated.content_fetched_at).toBe("2026-01-02T00:00:00Z");
    expect(updated.title).toBe(item.title);
    expect(updated.summary).toBe(item.summary);
    expect(updated.why_care).toBe(item.why_care);
    expect(updated.labels).toBe(item.labels);
  });

  it("records a failed fetch", () => {
    const updated = withArticle(item, {
      ...article,
      content_html: null,
      content_full: null,
      fetch_status: "blocked",
    });

    expect(updated.content_full).toBeNull();
    expect(updated.fetch_status).toBe("blocked");
  });
});
