import { describe, expect, it } from "vitest";

import { landingCopy } from "./landing-copy";

describe("landingCopy", () => {
  it("keeps the self-hosted landing page copy unchanged", () => {
    expect(landingCopy("local")).toEqual({
      eyebrow: "Self-hosted · local-first",
      description:
        "Tributary pulls RSS and Atom feeds into one quiet inbox, then lets you reshape the stream with small boxes: fetch, merge, filter, summarize, read. It runs on your machine, and the model boxes use Ollama locally.",
      privacyNote: "No account. No cloud. One SQLite file.",
      buildHeading: "Two local processes, one JSON spec.",
      buildBody:
        "The API is a small FastAPI service over SQLite. Feeds are fetched with httpx, parsed with feedparser and cleaned with trafilatura. Pipes are JSON specs executed by a box engine; the CLI and the API run the same spec. The reader is Next.js App Router with TanStack Query, and the editor is a React Flow canvas. AI boxes call Ollama through one local client and cache each answer in SQLite.",
      storageRow: "One SQLite file · no accounts",
      footerTagline: "Runs locally. No account, no algorithm.",
    });
  });

  it("drops the local-only claims in cloud mode", () => {
    const copy = landingCopy("cloud");
    const text = Object.values(copy).join(" ");

    expect(copy.eyebrow).toMatch(/^Hosted/);
    expect(copy.storageRow).toContain("PostgreSQL");
    expect(text).not.toContain("SQLite");
    expect(text).not.toContain("No account");
    expect(text).not.toContain("No cloud");
    expect(text).not.toContain("Runs locally");
  });
});
