import type { Edge, Node } from "@xyflow/react";

import type { PipeStep, SearchFreshness, SearchStep } from "./types";

export type BoxType = PipeStep["box"];

export type BoxGroup =
  | "Sources"
  | "Combine"
  | "Transform"
  | "Understand"
  | "Output";

export interface BoxDefinition {
  type: BoxType;
  label: string;
  group: BoxGroup;
  description: string;
  available: boolean;
}

export interface NodeRunState {
  status: "running" | "done" | "slow" | "error";
  seconds?: number;
  itemsOut?: number;
}

export interface BoxNodeData extends Record<string, unknown> {
  step: PipeStep;
  run?: NodeRunState;
}

export type BoxNode = Node<BoxNodeData, "box">;
export type BoxEdge = Edge;

export interface GraphResult {
  ok: true;
  steps: PipeStep[];
  nodeIds: string[];
}

export interface GraphError {
  ok: false;
  message: string;
  nodeId?: string;
}

const SEARCH_ENGINES = ["google_news", "google"] as const;
const SEARCH_FRESHNESS = ["day", "week", "month", "year"] as const;
const FILTER_FIELDS = ["title", "content", "link"] as const;
const DEDUPE_FIELDS = ["link", "guid", "title"] as const;
const SORT_FIELDS = ["published", "fetched_at", "title"] as const;
const SORT_ORDERS = ["asc", "desc"] as const;

export const BOX_DEFINITIONS: BoxDefinition[] = [
  {
    type: "fetch",
    label: "Fetch",
    group: "Sources",
    description: "Subscribe to one or more RSS or Atom feeds.",
    available: true,
  },
  {
    type: "search",
    label: "Search",
    group: "Sources",
    description: "Ask SerpAPI for items beyond your feeds.",
    available: true,
  },
  {
    type: "merge",
    label: "Merge",
    group: "Combine",
    description: "Join the source boxes earlier in the chain.",
    available: true,
  },
  {
    type: "dedupe",
    label: "Dedupe",
    group: "Combine",
    description: "Drop repeated links, GUIDs or titles.",
    available: true,
  },
  {
    type: "filter",
    label: "Filter",
    group: "Transform",
    description: "Keep items that contain a keyword.",
    available: true,
  },
  {
    type: "sort",
    label: "Sort",
    group: "Transform",
    description: "Order items by date or title.",
    available: true,
  },
  {
    type: "limit",
    label: "Limit",
    group: "Transform",
    description: "Keep only the first N items.",
    available: true,
  },
  {
    type: "fulltext",
    label: "Full text",
    group: "Output",
    description: "Fetch and store the full article text.",
    available: true,
  },
  {
    type: "summarize",
    label: "Summarize",
    group: "Understand",
    description: "Write a one-line summary with the local model.",
    available: true,
  },
  {
    type: "meaning",
    label: "Filter by meaning",
    group: "Understand",
    description: "Keep items that match a plain-language criterion.",
    available: true,
  },
  {
    type: "whycare",
    label: "Why you’d care",
    group: "Understand",
    description: "Explain why an item might matter to you.",
    available: true,
  },
];

export const AVAILABLE_BOX_TYPES = BOX_DEFINITIONS.filter(
  (definition) => definition.available,
);

export function boxDefinition(type: BoxType): BoxDefinition {
  return (
    BOX_DEFINITIONS.find((definition) => definition.type === type) ?? {
      type,
      label: type,
      group: "Transform",
      description: "",
      available: false,
    }
  );
}

export function defaultStep(type: BoxType): PipeStep {
  switch (type) {
    case "fetch":
      return { box: "fetch", urls: [] };
    case "search":
      return {
        box: "search",
        query: "",
        engine: "google_news",
        freshness: "week",
        max_results: 10,
        refine: true,
      };
    case "merge":
      return { box: "merge" };
    case "dedupe":
      return { box: "dedupe", by: "link" };
    case "filter":
      return {
        box: "filter",
        keyword: "",
        fields: ["title", "content"],
      };
    case "sort":
      return { box: "sort", by: "published", order: "desc" };
    case "limit":
      return { box: "limit", count: 10 };
    case "fulltext":
      return { box: "fulltext" };
    case "summarize":
      return { box: "summarize" };
    case "meaning":
      return { box: "meaning", criterion: "" };
    case "whycare":
      return { box: "whycare" };
  }
}

function cloneStep<T extends PipeStep>(step: T): T {
  return JSON.parse(JSON.stringify(step)) as T;
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function isOneOf<T extends string>(
  value: unknown,
  choices: readonly T[],
): value is T {
  return typeof value === "string" && choices.includes(value as T);
}

export function validateStep(step: PipeStep): string[] {
  const errors: string[] = [];

  switch (step.box) {
    case "fetch": {
      const urls = step.urls.map((url) => url.trim()).filter(Boolean);
      if (urls.length === 0) {
        errors.push("Add at least one feed URL.");
      }
      for (const url of urls) {
        if (!isHttpUrl(url)) {
          errors.push(`“${url}” is not an absolute http(s) URL.`);
        }
      }
      break;
    }
    case "search": {
      if (!step.query.trim()) {
        errors.push("Add a search request.");
      }
      if (step.engine !== undefined && !isOneOf(step.engine, SEARCH_ENGINES)) {
        errors.push("Choose a supported search engine.");
      }
      if (
        step.freshness !== undefined &&
        step.freshness !== null &&
        !isOneOf(step.freshness, SEARCH_FRESHNESS)
      ) {
        errors.push("Choose a supported freshness window.");
      }
      if (
        step.max_results !== undefined &&
        (!Number.isInteger(step.max_results) ||
          step.max_results < 1 ||
          step.max_results > 20)
      ) {
        errors.push("Max results must be a whole number from 1 to 20.");
      }
      if (step.gl !== undefined && !/^[a-z]{2}$/.test(step.gl)) {
        errors.push("Country must be a two-letter code.");
      }
      if (step.hl !== undefined && !/^[a-z]{2}$/.test(step.hl)) {
        errors.push("Language must be a two-letter code.");
      }
      break;
    }
    case "merge":
    case "fulltext":
    case "summarize":
    case "whycare":
      break;
    case "meaning":
      if (!step.criterion.trim()) {
        errors.push("Describe what should be kept.");
      }
      break;
    case "dedupe":
      if (step.by !== undefined && !isOneOf(step.by, DEDUPE_FIELDS)) {
        errors.push("Choose a supported dedupe field.");
      }
      break;
    case "filter":
      if (!step.keyword.trim()) {
        errors.push("Add a keyword.");
      }
      if (
        step.fields !== undefined &&
        (step.fields.length === 0 ||
          step.fields.some((field) => !isOneOf(field, FILTER_FIELDS)))
      ) {
        errors.push("Choose at least one field to search.");
      }
      break;
    case "sort":
      if (step.by !== undefined && !isOneOf(step.by, SORT_FIELDS)) {
        errors.push("Choose a supported sort field.");
      }
      if (step.order !== undefined && !isOneOf(step.order, SORT_ORDERS)) {
        errors.push("Choose ascending or descending order.");
      }
      break;
    case "limit":
      if (
        step.count !== undefined &&
        (!Number.isInteger(step.count) ||
          step.count < 1 ||
          step.count > 500)
      ) {
        errors.push("Limit must be a whole number from 1 to 500.");
      }
      break;
  }

  return errors;
}

export function stepsToGraph(
  steps: PipeStep[],
  positions?: Record<string, { x: number; y: number }>,
): { nodes: BoxNode[]; edges: BoxEdge[] } {
  const nodes: BoxNode[] = steps.map((step, index) => {
    const id = `step-${index}`;
    return {
      id,
      type: "box",
      position: positions?.[id] ?? { x: 60 + index * 260, y: 140 },
      data: { step: cloneStep(step) },
      style: { width: 200 },
    };
  });

  const edges: BoxEdge[] = steps.slice(1).map((_, index) => ({
    id: `edge-${index}-${index + 1}`,
    source: `step-${index}`,
    target: `step-${index + 1}`,
    type: "smoothstep",
    style: { strokeWidth: 1.5 },
  }));

  return { nodes, edges };
}

export function graphToSteps(nodes: BoxNode[], edges: BoxEdge[]): GraphResult | GraphError {
  if (nodes.length === 0) {
    return {
      ok: false,
      message: "Add at least one box before saving.",
    };
  }

  const byId = new Map<string, BoxNode>();
  for (const node of nodes) {
    if (byId.has(node.id)) {
      return { ok: false, message: `Duplicate box id “${node.id}”.`, nodeId: node.id };
    }
    byId.set(node.id, node);
  }

  const incoming = new Map<string, BoxEdge>();
  const outgoing = new Map<string, BoxEdge>();
  const seenPairs = new Set<string>();

  for (const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) {
      return {
        ok: false,
        message: "A wire points at a box that no longer exists.",
      };
    }
    if (edge.source === edge.target) {
      return {
        ok: false,
        message: "A box cannot connect to itself.",
        nodeId: edge.source,
      };
    }
    const pair = `${edge.source}->${edge.target}`;
    if (seenPairs.has(pair)) {
      return { ok: false, message: "Two boxes are connected twice." };
    }
    seenPairs.add(pair);

    if (outgoing.has(edge.source)) {
      return {
        ok: false,
        message: "A box can only feed one next box. MVP pipes are a single chain.",
        nodeId: edge.source,
      };
    }
    if (incoming.has(edge.target)) {
      return {
        ok: false,
        message: "A box can only receive from one previous box. MVP pipes are a single chain.",
        nodeId: edge.target,
      };
    }
    outgoing.set(edge.source, edge);
    incoming.set(edge.target, edge);
  }

  const starts = nodes.filter((node) => !incoming.has(node.id));
  const ends = nodes.filter((node) => !outgoing.has(node.id));
  if (starts.length === 0 || ends.length === 0) {
    return {
      ok: false,
      message: "The boxes form a loop. Remove the wire that closes it.",
    };
  }
  if (starts.length !== 1 || ends.length !== 1) {
    return {
      ok: false,
      message: "Some boxes are not connected to the main path.",
    };
  }

  const ordered: BoxNode[] = [];
  const visited = new Set<string>();
  let current: BoxNode | undefined = starts[0];

  while (current) {
    if (visited.has(current.id)) {
      return {
        ok: false,
        message: "The boxes form a loop. Remove the wire that closes it.",
        nodeId: current.id,
      };
    }
    visited.add(current.id);
    ordered.push(current);

    const next = outgoing.get(current.id);
    current = next ? byId.get(next.target) : undefined;
  }

  if (ordered.length !== nodes.length) {
    return {
      ok: false,
      message: "Some boxes are not connected to the main path.",
    };
  }

  const first = ordered[0].data.step;
  if (first.box !== "fetch" && first.box !== "search") {
    return {
      ok: false,
      message: "Start the pipe with a Fetch or Search box.",
      nodeId: ordered[0].id,
    };
  }

  const steps: PipeStep[] = [];
  for (const node of ordered) {
    const step = cloneStep(node.data.step);
    const errors = validateStep(step);
    if (errors.length > 0) {
      return {
        ok: false,
        message: errors[0],
        nodeId: node.id,
      };
    }
    steps.push(step);
  }

  return { ok: true, steps, nodeIds: ordered.map((node) => node.id) };
}

export function searchPreviewLabel(step: SearchStep): string {
  const parts: string[] = [step.engine ?? "google_news"];
  if (step.freshness) {
    parts.push(step.freshness);
  }
  if (step.max_results !== undefined) {
    parts.push(`${step.max_results} results`);
  }
  return parts.join(" · ");
}

export function stepLabel(step: PipeStep): string {
  return boxDefinition(step.box).label;
}

export function freshnessOptions(): readonly SearchFreshness[] {
  return SEARCH_FRESHNESS;
}
