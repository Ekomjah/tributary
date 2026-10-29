const HTML_TAG = /<[a-z][\s\S]*>/i;

export function htmlToText(value: string): string {
  if (!value) {
    return "";
  }

  if (!HTML_TAG.test(value)) {
    return value.trim();
  }

  if (typeof window === "undefined") {
    return value
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  const parsed = new DOMParser().parseFromString(value, "text/html");
  parsed.querySelectorAll("script, style, noscript").forEach((node) => node.remove());
  parsed.querySelectorAll("br").forEach((node) => node.replaceWith("\n"));
  parsed.querySelectorAll("li").forEach((node) => node.prepend("• "));
  parsed
    .querySelectorAll("p, div, li, blockquote, pre, h1, h2, h3, h4, h5, h6")
    .forEach((node) => node.append("\n\n"));

  return (parsed.body.textContent ?? "")
    .replace(/\r/g, "")
    .replace(/[ \t]+\n/g, "\n")
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

export function contentParagraphs(value: string): string[] {
  return htmlToText(value)
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
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
