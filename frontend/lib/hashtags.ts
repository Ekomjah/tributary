export interface HashtagPart {
  type: "text" | "tag";
  value: string;
}

const HASHTAG_PATTERN =
  /(?<![\p{L}\p{N}_&#/=%.:@-])#([\p{L}\p{N}_][\p{L}\p{N}_-]{0,49})(?![\p{L}\p{N}_-])/gu;

const HAS_LETTER = /\p{L}/u;
const HEX_COLOR = /^(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
const SKIP_TAGS = new Set([
  "a",
  "code",
  "kbd",
  "pre",
  "samp",
  "script",
  "style",
  "textarea",
]);
const TAG_NAME = /^<\s*\/?\s*([a-zA-Z][\w:-]*)/;

function isHashtag(tag: string): boolean {
  return HAS_LETTER.test(tag) && !HEX_COLOR.test(tag);
}

export function hashtagHref(tag: string): string {
  return `/feeds?q=${encodeURIComponent(`#${tag}`)}`;
}

function renderHashtag(tag: string): string {
  const label = `#${tag}`;
  return `<a class="article-hashtag" href="${hashtagHref(
    tag,
  )}" data-hashtag="${tag}" title="Search for ${label}">${label}</a>`;
}

export function splitHashtags(value: string): HashtagPart[] {
  const parts: HashtagPart[] = [];
  let cursor = 0;

  for (const match of value.matchAll(HASHTAG_PATTERN)) {
    const index = match.index ?? 0;
    const tag = match[1];
    if (!isHashtag(tag)) {
      continue;
    }

    if (index > cursor) {
      parts.push({ type: "text", value: value.slice(cursor, index) });
    }
    parts.push({ type: "tag", value: tag });
    cursor = index + match[0].length;
  }

  if (cursor < value.length) {
    parts.push({ type: "text", value: value.slice(cursor) });
  }

  return parts.length > 0 ? parts : [{ type: "text", value }];
}

function hashtagifyText(value: string): string {
  return splitHashtags(value)
    .map((part) =>
      part.type === "tag" ? renderHashtag(part.value) : part.value,
    )
    .join("");
}

function findTagEnd(html: string, start: number): number {
  let quote = "";

  for (let index = start + 1; index < html.length; index += 1) {
    const character = html[index];

    if (quote) {
      if (character === quote) {
        quote = "";
      }
      continue;
    }

    if (character === '"' || character === "'") {
      quote = character;
      continue;
    }

    if (character === ">") {
      return index + 1;
    }
  }

  return -1;
}

/**
 * Turn hashtag-like text in an already sanitized HTML fragment into tag chips.
 *
 * The tokenizer walks the markup instead of running a regex over the whole
 * string, so tags and attribute values are never rewritten. Text inside links,
 * code blocks and scripts keeps its original form. The output is deterministic,
 * so server rendering and hydration agree.
 */
export function hashtagifyHtml(html: string): string {
  if (!html || !html.includes("#")) {
    return html;
  }

  let output = "";
  let cursor = 0;
  let skipDepth = 0;

  while (cursor < html.length) {
    const tagStart = html.indexOf("<", cursor);

    if (tagStart === -1) {
      const text = html.slice(cursor);
      output += skipDepth > 0 ? text : hashtagifyText(text);
      break;
    }

    if (tagStart > cursor) {
      const text = html.slice(cursor, tagStart);
      output += skipDepth > 0 ? text : hashtagifyText(text);
    }

    if (html.startsWith("<!--", tagStart)) {
      const commentEnd = html.indexOf("-->", tagStart + 4);
      const end = commentEnd === -1 ? -1 : commentEnd + 3;
      if (end === -1) {
        output += html.slice(tagStart);
        break;
      }
      output += html.slice(tagStart, end);
      cursor = end;
      continue;
    }

    const tagEnd = findTagEnd(html, tagStart);
    if (tagEnd === -1) {
      const text = html.slice(tagStart);
      output += skipDepth > 0 ? text : hashtagifyText(text);
      break;
    }

    const tag = html.slice(tagStart, tagEnd);
    const match = tag.match(TAG_NAME);
    if (match) {
      const name = match[1].toLowerCase();
      if (SKIP_TAGS.has(name)) {
        const closing = /^<\s*\//.test(tag);
        const selfClosing = /\/\s*>$/.test(tag);
        if (closing) {
          skipDepth = Math.max(0, skipDepth - 1);
        } else if (!selfClosing) {
          skipDepth += 1;
        }
      }
    }

    output += tag;
    cursor = tagEnd;
  }

  return output;
}
