import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  CircleCheck,
  Filter,
  Lock,
  Rss,
  Sparkles,
  Workflow,
  type LucideIcon,
} from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Tributary — a feed reader with pipes",
  description:
    "A self-hosted feed reader and visual pipe builder. RSS and Atom in, a quiet inbox out, with local model boxes when you want them.",
};

const FEATURES: {
  icon: LucideIcon;
  title: string;
  body: string;
}[] = [
  {
    icon: BookOpen,
    title: "A reader that stays quiet",
    body: "Unread, starred and labeled items, with keyboard shortcuts for moving, starring and marking read. No algorithm decides what you see.",
  },
  {
    icon: Workflow,
    title: "Pipes, not rules",
    body: "Drag Fetch, Merge, Dedupe, Filter, Sort, Limit and Full text boxes onto a canvas. Save the chain as JSON you can read, edit and run from the CLI.",
  },
  {
    icon: Sparkles,
    title: "A local model in the chain",
    body: "Summarize each item, keep only what matches a meaning, or add a “why you’d care” line. The AI boxes call Ollama on the same machine.",
  },
];

const BUILD_ROWS: [string, string][] = [
  [
    "Reader",
    "Next.js 16 App Router · React 19 · Tailwind CSS · TanStack Query",
  ],
  ["Editor", "React Flow canvas · JSON pipe specs"],
  ["API", "FastAPI · SQLAlchemy · SQLite"],
  ["Fetching", "httpx · feedparser · trafilatura"],
  ["Model", "Ollama · summaries, meaning filters, why-care"],
  ["Search", "SerpAPI, optional · refined by the local model"],
  ["Storage", "One SQLite file · no accounts"],
];

const PIPE_STEPS: {
  icon: LucideIcon;
  title: string;
  detail: string;
  ai?: boolean;
}[] = [
  { icon: Rss, title: "Fetch", detail: "2 feeds · RSS / Atom" },
  { icon: Filter, title: "Filter", detail: "keyword: databases" },
  {
    icon: Sparkles,
    title: "Summarize",
    detail: "local model · gemma3:1b",
    ai: true,
  },
  { icon: BookOpen, title: "Read", detail: "12 items · unread" },
];

function PipeBox({
  icon: Icon,
  title,
  detail,
  ai,
}: {
  icon: LucideIcon;
  title: string;
  detail: string;
  ai?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative w-full max-w-[300px] border border-line bg-canvas",
        ai && "border-t-[3px] border-t-accent",
      )}
    >
      <div className="flex h-7 items-center gap-1.5 border-b border-divider bg-chrome px-2">
        <Icon className="size-3.5 shrink-0 text-muted" aria-hidden="true" />
        <span className="text-[11px] font-bold uppercase tracking-[0.06em]">
          {title}
        </span>
        {ai && (
          <span className="ml-auto border border-accent px-1 py-0.5 text-[9px] font-bold uppercase leading-none text-accent">
            AI
          </span>
        )}
      </div>
      <div className="px-2 py-1.5 font-mono text-[10px] text-muted">
        {detail}
      </div>
      <span
        className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 border border-faint bg-canvas"
        aria-hidden="true"
      />
      <span
        className="absolute -bottom-1 left-1/2 size-2 -translate-x-1/2 border border-faint bg-canvas"
        aria-hidden="true"
      />
    </div>
  );
}

function PipelineDiagram() {
  return (
    <figure className="border border-divider bg-sidebar p-5 [background-image:radial-gradient(var(--divider)_1px,transparent_1px)] [background-size:16px_16px]">
      <div className="flex items-center justify-between gap-3 border-b border-divider pb-3 font-mono text-[10px] text-faint">
        <span>morning-read.json</span>
        <span className="flex items-center gap-1 text-success">
          <CircleCheck className="size-3" aria-hidden="true" />
          Done · 12 items
        </span>
      </div>

      <div className="flex flex-col items-center py-4">
        {PIPE_STEPS.map((step, index) => (
          <div key={step.title} className="flex w-full flex-col items-center">
            <PipeBox {...step} />
            {index < PIPE_STEPS.length - 1 && (
              <div className="h-5 w-px bg-line" aria-hidden="true" />
            )}
          </div>
        ))}
      </div>

      <figcaption className="border-t border-divider pt-3 text-[11px] leading-4 text-muted">
        A pipe is a chain of boxes. Each box takes a list of items and returns a
        list.
      </figcaption>
    </figure>
  );
}

export default function Home() {
  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <header className="border-b border-divider bg-canvas">
        <div className="mx-auto flex h-14 max-w-[1040px] items-center gap-6 px-6 max-[700px]:px-4">
          <Link
            href="/"
            className="text-[20px] font-bold leading-none text-danger hover:no-underline hover:opacity-80"
          >
            Tributary
          </Link>
          <nav
            aria-label="Primary"
            className="ml-auto flex items-center gap-5 text-[12px] max-[700px]:gap-3"
          >
            <Link href="/feeds" className="text-ink hover:text-accent">
              Reader
            </Link>
            <Link href="/pipes" className="text-ink hover:text-accent">
              Pipes
            </Link>
            <a
              href="#built"
              className="text-muted hover:text-ink max-[520px]:hidden"
            >
              How it’s built
            </a>
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto max-w-[1040px] px-6 pb-14 pt-12 max-[700px]:px-4 max-[700px]:pt-8">
          <div className="grid items-center gap-12 lg:grid-cols-[1.05fr_0.95fr]">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                Self-hosted · local-first
              </p>
              <h1 className="mt-3 max-w-[560px] text-[40px] font-bold leading-[1.08] tracking-[-0.02em] text-ink max-[700px]:text-[32px]">
                A feed reader with pipes.
              </h1>
              <p className="mt-4 max-w-[540px] text-[15px] leading-6 text-muted">
                Tributary pulls RSS and Atom feeds into one quiet inbox, then
                lets you reshape the stream with small boxes: fetch, merge,
                filter, summarize, read. It runs on your machine, and the model
                boxes use Ollama locally.
              </p>

              <div className="mt-6 flex flex-wrap items-center gap-2">
                <Link
                  href="/feeds"
                  className={cn(
                    buttonVariants({ variant: "primary" }),
                    "h-9 px-5",
                  )}
                >
                  Open the reader
                  <ArrowRight className="size-3.5" aria-hidden="true" />
                </Link>
                <Link
                  href="/pipes"
                  className={cn(
                    buttonVariants({ variant: "secondary" }),
                    "h-9 px-4",
                  )}
                >
                  Build a pipe
                </Link>
              </div>

              <p className="mt-5 flex items-center gap-1.5 text-[11px] text-faint">
                <Lock className="size-3.5" aria-hidden="true" />
                No account. No cloud. One SQLite file.
              </p>
            </div>

            <PipelineDiagram />
          </div>
        </section>

        <section className="border-t border-divider">
          <div className="mx-auto grid max-w-[1040px] px-6 md:grid-cols-3 max-[700px]:px-4">
            {FEATURES.map((feature, index) => {
              const Icon = feature.icon;
              return (
                <div
                  key={feature.title}
                  className={cn(
                    "py-8 md:px-6",
                    index === 0 && "md:pl-0",
                    index === FEATURES.length - 1 && "md:pr-0",
                    index > 0 &&
                      "border-t border-divider md:border-l md:border-t-0",
                  )}
                >
                  <Icon className="size-4 text-muted" aria-hidden="true" />
                  <h2 className="mt-3 text-[15px] font-bold text-ink">
                    {feature.title}
                  </h2>
                  <p className="mt-1.5 text-[13px] leading-5 text-muted">
                    {feature.body}
                  </p>
                </div>
              );
            })}
          </div>
        </section>

        <section id="built" className="border-t border-divider">
          <div className="mx-auto grid max-w-[1040px] gap-10 px-6 py-12 md:grid-cols-[0.9fr_1.1fr] max-[700px]:px-4">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                How it was built
              </p>
              <h2 className="mt-2 text-[20px] font-bold text-ink">
                Two local processes, one JSON spec.
              </h2>
              <p className="mt-3 max-w-[440px] text-[13px] leading-5 text-muted">
                The API is a small FastAPI service over SQLite. Feeds are
                fetched with httpx, parsed with feedparser and cleaned with
                trafilatura. Pipes are JSON specs executed by a box engine; the
                CLI and the API run the same spec. The reader is Next.js App
                Router with TanStack Query, and the editor is a React Flow
                canvas. AI boxes call Ollama through one local client and cache
                each answer in SQLite.
              </p>
            </div>

            <dl className="border-t border-divider">
              {BUILD_ROWS.map(([label, value]) => (
                <div
                  key={label}
                  className="grid grid-cols-[120px_1fr] gap-4 border-b border-divider py-2.5 max-[520px]:grid-cols-1 max-[520px]:gap-0.5"
                >
                  <dt className="font-mono text-[10px] uppercase tracking-[0.08em] text-faint">
                    {label}
                  </dt>
                  <dd className="text-[13px] leading-5 text-ink">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="border-t border-divider">
          <div className="mx-auto flex max-w-[1040px] flex-col gap-6 px-6 py-10 md:flex-row md:items-end md:justify-between max-[700px]:px-4">
            <div>
              <h2 className="text-[20px] font-bold text-ink">
                Start with the reader.
              </h2>
              <p className="mt-1 text-[13px] text-muted">
                Build a pipe when you want to reshape the stream.
              </p>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-[13px] font-bold">
              <Link
                href="/feeds"
                className="inline-flex items-center gap-1 text-accent hover:underline"
              >
                Open the reader
                <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
              <Link
                href="/pipes"
                className="inline-flex items-center gap-1 text-accent hover:underline"
              >
                Open the pipes
                <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-divider">
        <div className="mx-auto flex max-w-[1040px] flex-wrap items-center justify-between gap-2 px-6 py-5 text-[11px] text-faint max-[700px]:px-4">
          <span>Tributary · MIT</span>
          <span>Runs locally. No account, no algorithm.</span>
        </div>
      </footer>
    </div>
  );
}
