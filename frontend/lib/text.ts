const HTML_TAG = /<[a-z][\s\S]*>/i;

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  mdash: "—",
  ndash: "–",
  hellip: "…",
  lsquo: "‘",
  rsquo: "’",
  ldquo: "“",
  rdquo: "”",
  laquo: "«",
  raquo: "»",
  middot: "·",
  bull: "•",
  copy: "©",
  reg: "®",
  trade: "™",
  deg: "°",
  times: "×",
  divide: "÷",
  eacute: "é",
  egrave: "è",
  agrave: "à",
  ccedil: "ç",
  uuml: "ü",
  ouml: "ö",
  auml: "ä",
  szlig: "ß",
};

const BLOCK_END =
  /<\/(?:address|article|aside|blockquote|dd|div|dl|dt|fieldset|figcaption|figure|footer|form|h[1-6]|header|main|nav|ol|p|pre|section|table|tbody|tfoot|thead|tr|ul)>/gi;

function decodeEntities(value: string): string {
  return value.replace(
    /&(#x?[0-9a-f]+|[a-z][a-z0-9]+);/gi,
    (match, entity: string) => {
      if (entity.startsWith("#")) {
        const hexadecimal = entity[1]?.toLowerCase() === "x";
        const codePoint = Number.parseInt(
          entity.slice(hexadecimal ? 2 : 1),
          hexadecimal ? 16 : 10,
        );
        if (
          !Number.isFinite(codePoint) ||
          codePoint <= 0 ||
          codePoint > 0x10ffff
        ) {
          return match;
        }
        try {
          return String.fromCodePoint(codePoint);
        } catch {
          return match;
        }
      }
      return NAMED_ENTITIES[entity.toLowerCase()] ?? match;
    },
  );
}

export function htmlToText(value: string): string {
  if (!value) {
    return "";
  }

  if (!HTML_TAG.test(value)) {
    return decodeEntities(value)
      .replace(/\r/g, "")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n[ \t]*\n/g, "\n\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  // Keep this path string-only so server rendering and hydration produce the
  // same paragraph boundaries. DOMParser is not available during SSR.
  const text = value
    .replace(
      /<(script|style|noscript|template)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,
      "",
    )
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<hr\b[^>]*\/?>/gi, "\n\n")
    .replace(/<li\b[^>]*>/gi, "• ")
    .replace(/<\/li\s*>/gi, "\n")
    .replace(/<\/(?:td|th)\s*>/gi, " ")
    .replace(BLOCK_END, "\n\n")
    .replace(/<[^>]+>/g, "");

  return decodeEntities(text)
    .replace(/\r/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]*\n/g, "\n\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function plainText(value: string): string {
  return htmlToText(value).replace(/\s+/g, " ").trim();
}

export function excerpt(value: string, length = 190): string {
  const text = plainText(value);
  if (text.length <= length) {
    return text;
  }
  return `${text.slice(0, length).trimEnd()}…`;
}

function titleKey(value: string): string {
  return plainText(value)
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function titlesMatch(left: string, right: string): boolean {
  const first = titleKey(left);
  const second = titleKey(right);
  if (!first || !second) {
    return false;
  }
  if (first === second) {
    return true;
  }

  const [shorter, longer] =
    first.length <= second.length ? [first, second] : [second, first];
  return (
    shorter.length >= 12 &&
    longer.startsWith(shorter) &&
    shorter.length / longer.length >= 0.6
  );
}

function groupLines(lines: string[]): string[] {
  const blocks: string[] = [];
  let list: string[] = [];

  const flush = () => {
    if (list.length > 0) {
      blocks.push(list.join("\n"));
      list = [];
    }
  };

  for (const line of lines) {
    if (/^(?:[-*•]|\d+[.)])\s+/.test(line)) {
      list.push(line);
    } else {
      flush();
      blocks.push(line);
    }
  }
  flush();
  return blocks;
}

export interface ContentBlock {
  type: "paragraph" | "code";
  text: string;
  language?: string;
}

const CODE_FENCE = /^\s*(```|~~~)\s*([A-Za-z0-9_+.#-]*)\s*$/;
const CLOSING_FENCE = /^\s*(```|~~~)\s*$/;

export function contentParagraphs(
  value: string,
  title?: string | null,
): string[] {
  if (!value.trim()) {
    return [];
  }

  const sourceIsHtml = HTML_TAG.test(value);
  const text = htmlToText(value);
  if (!text) {
    return [];
  }

  let paragraphs: string[];
  if (sourceIsHtml || text.includes("\n\n")) {
    // Real block boundaries became blank lines. A single newline is a <br>
    // inside one paragraph or a list item, so it must stay in its block.
    paragraphs = text.split(/\n{2,}/);
  } else {
    // Trafilatura's plain-text output puts one block per line with no blank
    // lines, so every line becomes a paragraph. Consecutive list lines stay
    // together and keep their leading markers.
    paragraphs = groupLines(
      text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
    );
  }

  paragraphs = paragraphs.map((paragraph) => paragraph.trim()).filter(Boolean);

  if (title && paragraphs.length > 0 && titlesMatch(paragraphs[0], title)) {
    paragraphs = paragraphs.slice(1);
  }

  return paragraphs;
}

/**
 * Split article text into prose and fenced code blocks.
 *
 * The HTML path already carries real <pre> markup, so it stays paragraph-only.
 * Plain extracted text sometimes keeps triple-backtick fences; those become
 * code blocks so the reader can render them as code instead of prose.
 */
export function contentBlocks(
  value: string,
  title?: string | null,
): ContentBlock[] {
  if (!value.trim()) {
    return [];
  }

  if (HTML_TAG.test(value)) {
    return contentParagraphs(value, title).map((text) => ({
      type: "paragraph",
      text,
    }));
  }

  const lines = htmlToText(value).split("\n");
  const blocks: ContentBlock[] = [];
  let prose: string[] = [];
  let firstProse = true;

  const flushProse = () => {
    if (prose.length === 0) {
      return;
    }
    const paragraphs = contentParagraphs(
      prose.join("\n"),
      firstProse ? title : null,
    );
    firstProse = false;
    blocks.push(
      ...paragraphs.map((text) => ({ type: "paragraph" as const, text })),
    );
    prose = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const fence = lines[index].match(CODE_FENCE);
    if (!fence) {
      prose.push(lines[index]);
      continue;
    }

    flushProse();
    const marker = fence[1];
    const language = fence[2] || undefined;
    const code: string[] = [];
    index += 1;
    while (index < lines.length) {
      const closing = lines[index].match(CLOSING_FENCE);
      if (closing && closing[1] === marker) {
        break;
      }
      code.push(lines[index]);
      index += 1;
    }

    const text = code.join("\n");
    if (text.trim()) {
      blocks.push({ type: "code", text, language });
    }
  }

  flushProse();
  return blocks;
}

export function parseDate(value: string): Date {
  const hasZone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function formatRelative(value: string | null): string {
  if (!value) {
    return "No date";
  }

  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) {
    return "No date";
  }

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) {
    return "just now";
  }

  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }

  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }

  const days = Math.round(hours / 24);
  if (days < 7) {
    return `${days}d ago`;
  }

  const sameYear = date.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: sameYear ? undefined : "numeric",
  }).format(date);
}

export function formatFullDate(value: string | null): string {
  if (!value) {
    return "No date";
  }

  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) {
    return "No date";
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function readingMinutes(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  if (words === 0) {
    return 0;
  }
  return Math.max(1, Math.round(words / 220));
}
