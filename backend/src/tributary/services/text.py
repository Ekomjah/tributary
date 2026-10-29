from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

import nh3
from bs4 import BeautifulSoup

__all__ = [
    "html_to_text",
    "normalize_text",
    "readable_title",
    "sanitize_html",
    "unescape_all",
]

# Tags whose boundaries should read as paragraph breaks in plain text.
_BLOCK_TAGS = (
    "address",
    "article",
    "aside",
    "blockquote",
    "body",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "html",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
)
_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "object")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_SPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# A deliberately conservative reading surface: prose, lists, quotes, code,
# simple tables, and remote images. Embeds, forms, inline SVG, and inline styles
# are dropped.
_ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "cite",
    "code",
    "del",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "q",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "loading", "decoding", "referrerpolicy"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
_URL_SCHEMES = {"http", "https", "mailto"}
_IMAGE_SCHEMES = {"http", "https"}
_TRACKING_PIXEL_MAX = 2


def unescape_all(value: str, *, max_passes: int = 5) -> str:
    """Decode HTML entities until the text stops changing.

    Feed generators commonly double-escape titles and summaries, so a single
    ``html.unescape`` leaves literal ``&#8217;`` sequences behind.
    """

    text = value
    for _ in range(max_passes):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return normalize_text(text)


def normalize_text(value: str) -> str:
    """Return NFC text with normalized line endings and no control characters."""

    text = unicodedata.normalize("NFC", value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    return _CONTROL.sub("", text)


def readable_title(value: str) -> str:
    """Turn a feed or item title into one clean line of plain text."""

    return " ".join(html_to_text(value).split())


def _dimension(value: object) -> int | None:
    """Read the leading integer from an HTML width or height attribute."""

    match = re.match(r"\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _clean_images(soup: BeautifulSoup, base_url: str | None) -> None:
    """Resolve safe image sources and force privacy-preserving attributes.

    Only remote http(s) images survive. Relative URLs are resolved against the
    article URL, obvious tracking pixels are removed, and every kept image is
    lazy-loaded without a referrer.
    """

    for image in soup.find_all("img"):
        src = str(image.get("src") or "").strip()
        if not src:
            image.decompose()
            continue

        if base_url:
            src = urljoin(base_url, src)
        if urlsplit(src).scheme.lower() not in _IMAGE_SCHEMES:
            image.decompose()
            continue

        width = _dimension(image.get("width"))
        height = _dimension(image.get("height"))
        if (
            width is not None
            and height is not None
            and width <= _TRACKING_PIXEL_MAX
            and height <= _TRACKING_PIXEL_MAX
        ):
            image.decompose()
            continue

        image["src"] = src
        image["loading"] = "lazy"
        image["decoding"] = "async"
        image["referrerpolicy"] = "no-referrer"


def sanitize_html(value: str, *, base_url: str | None = None) -> str | None:
    """Return a safe HTML fragment for display, or ``None`` when there is none.

    Relative links and image sources are resolved against ``base_url`` before
    the fragment is cleaned with nh3. Remote images keep only safe source and
    alt text attributes. Plain text and double-escaped markup produce ``None``
    so the reader keeps rendering the plain-text summary instead.
    """

    if not value or not value.strip():
        return None

    soup = BeautifulSoup(value, "html.parser")
    if soup.find() is None:
        return None

    if base_url:
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if href:
                link["href"] = urljoin(base_url, href)

    _clean_images(soup, base_url)

    cleaned = nh3.clean(
        str(soup),
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener noreferrer",
        strip_comments=True,
    ).strip()
    if not cleaned or BeautifulSoup(cleaned, "html.parser").find() is None:
        return None
    return cleaned


def html_to_text(value: str) -> str:
    """Convert feed HTML to readable plain text with paragraph boundaries.

    Inline markup is flattened, scripts and styles are dropped, and block-level
    elements become blank-line-separated paragraphs. The result is NFC text with
    HTML entities decoded.
    """

    if not value:
        return ""

    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all("br"):
        tag.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n\n")
        tag.insert_after("\n\n")

    text = soup.get_text("")
    lines = [_INLINE_SPACE.sub(" ", line).strip() for line in text.split("\n")]

    cleaned: list[str] = []
    for line in lines:
        if line:
            cleaned.append(line)
        elif cleaned and cleaned[-1] != "":
            cleaned.append("")

    return unescape_all(_BLANK_LINES.sub("\n\n", "\n".join(cleaned)).strip())
