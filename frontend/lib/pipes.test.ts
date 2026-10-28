import { describe, expect, it } from "vitest";

import {
  defaultStep,
  graphToSteps,
  stepsToGraph,
  validateStep,
  type BoxNode,
} from "./pipes";
import type { PipeStep } from "./types";

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
