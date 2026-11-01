import type { AuthMode } from "./auth-config";

export interface LandingCopy {
  eyebrow: string;
  description: string;
  privacyNote: string;
  buildHeading: string;
  buildBody: string;
  storageRow: string;
  footerTagline: string;
}

const LOCAL_COPY: LandingCopy = {
  eyebrow: "Self-hosted · local-first",
  description:
    "Tributary pulls RSS and Atom feeds into one quiet inbox, then lets you reshape the stream with small boxes: fetch, merge, filter, summarize, read. It runs on your machine, and the model boxes use Ollama locally.",
  privacyNote: "No account. No cloud. One SQLite file.",
  buildHeading: "Two local processes, one JSON spec.",
  buildBody:
    "The API is a small FastAPI service over SQLite. Feeds are fetched with httpx, parsed with feedparser and cleaned with trafilatura. Pipes are JSON specs executed by a box engine; the CLI and the API run the same spec. The reader is Next.js App Router with TanStack Query, and the editor is a React Flow canvas. AI boxes call Ollama through one local client and cache each answer in SQLite.",
  storageRow: "One SQLite file · no accounts",
  footerTagline: "Runs locally. No account, no algorithm.",
};

const CLOUD_COPY: LandingCopy = {
  eyebrow: "Hosted · no algorithm",
  description:
    "Tributary pulls RSS and Atom feeds into one quiet inbox, then lets you reshape the stream with small boxes: fetch, merge, filter, summarize, read. Your library lives in the cloud, behind your own account.",
  privacyNote: "Private library. Sign in with your own account.",
  buildHeading: "Two processes, one JSON spec.",
  buildBody:
    "The API is a small FastAPI service over PostgreSQL. Feeds are fetched with httpx, parsed with feedparser and cleaned with trafilatura. Pipes are JSON specs executed by a box engine; the CLI and the API run the same spec. The reader is Next.js App Router with TanStack Query, and the editor is a React Flow canvas. AI boxes call a model through one client and cache each answer in PostgreSQL.",
  storageRow: "PostgreSQL · one library per account",
  footerTagline: "Hosted. One account, no algorithm.",
};

/** Copy that changes between a self-hosted install and the hosted reader. */
export function landingCopy(mode: AuthMode): LandingCopy {
  return mode === "cloud" ? CLOUD_COPY : LOCAL_COPY;
}
