from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

import nh3
from bs4 import BeautifulSoup, NavigableString, Tag

__all__ = [
    "clean_byline",
    "clean_meta_text",
    "html_to_text",
    "image_alt_for",
    "is_promo_image",
    "leading_image",
    "normalize_text",
    "readable_title",
    "safe_image_url",
    "sanitize_html",
    "strip_leading_image",
    "titles_match",
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
    "caption",
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
_PROMO_IMAGE_TOKEN = re.compile(
    r"(?:^|[/_.-])(?:ad|ads|advert|advertisement|banner|badge|cookie|icon|logo|"
    r"newsletter|pixel|promo|promotion|sponsor|subscribe|tracking)(?:[/_.-]|$)",
    re.IGNORECASE,
)

# Layout wrappers that carry no meaning once the fragment is rendered inside the
# reader's prose column. They are folded into paragraphs before sanitizing so a
# feed's div-based paragraphs keep their structure after nh3 drops the divs.
_LAYOUT_TAGS = (
    "address",
    "article",
    "aside",
    "center",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "footer",
    "header",
    "main",
    "section",
)
# Blocks that should keep their own boundary and never be wrapped in a <p>.
_FLOW_TAGS = (
    "blockquote",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "ol",
    "p",
    "pre",
    "table",
    "ul",
)
# Elements that already own their text and must not gain a nested paragraph.
_NO_PARAGRAPH_PARENTS = (
    "a",
    "code",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "pre",
)


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


def _title_key(value: str) -> str:
    """Fold a title to letters, numbers and single spaces for comparison."""

    text = normalize_text(html_to_text(value)).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def titles_match(left: str | None, right: str | None) -> bool:
    """Return whether two titles are the same page headline.

    Feed titles often carry a site suffix while the extracted page title does
    not. Compare the normalised forms and allow one to be a conservative
    prefix of the other so the reader does not show the headline twice.
    """

    first = _title_key(left or "")
    second = _title_key(right or "")
    if not first or not second:
        return False
    if first == second:
        return True

    shorter, longer = sorted((first, second), key=len)
    return len(shorter) >= 12 and longer.startswith(shorter) and len(shorter) / len(longer) >= 0.6


def _node_has_text(node: object) -> bool:
    """Return whether a node contributes readable text to a paragraph."""

    if isinstance(node, NavigableString):
        return bool(str(node).strip())
    if isinstance(node, Tag):
        if node.name in {"br", "hr", "img"}:
            return False
        return bool(node.get_text(strip=True))
    return False


def _wrap_loose_inline(soup: BeautifulSoup) -> None:
    """Wrap top-level inline runs in paragraphs without wrapping lead images."""

    group: list[NavigableString | Tag] = []

    def flush() -> None:
        if not group:
            return
        if any(_node_has_text(node) for node in group):
            paragraph = soup.new_tag("p")
            first = group[0]
            first.insert_before(paragraph)
            for node in group:
                paragraph.append(node.extract())
        group.clear()

    for child in list(soup.contents):
        if isinstance(child, Tag) and child.name in _FLOW_TAGS:
            flush()
        else:
            group.append(child)
    flush()


def _normalize_structure(soup: BeautifulSoup) -> None:
    """Give a feed fragment the block structure the reader styles expect."""

    for document_tag in soup.find_all(["html", "body"]):
        document_tag.unwrap()

    for tag in reversed(soup.find_all(_LAYOUT_TAGS)):
        if tag.find_parent(_NO_PARAGRAPH_PARENTS) is not None:
            tag.unwrap()
        elif tag.find(_FLOW_TAGS, recursive=False) is not None:
            tag.unwrap()
        else:
            tag.name = "p"

    for pre in soup.find_all("pre"):
        inner = pre.find("pre")
        if inner is not None:
            inner.unwrap()

    _wrap_loose_inline(soup)

    for paragraph in soup.find_all("p"):
        if not paragraph.get_text(strip=True) and paragraph.find(["figure", "img"]) is None:
            paragraph.decompose()

    # The item title is the page's only h1; headings inside the body start at h2.
    for heading in soup.find_all("h1"):
        heading.name = "h2"


def _dimension(value: object) -> int | None:
    """Read the leading integer from an HTML width or height attribute."""

    match = re.match(r"\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def clean_meta_text(value: str | None, *, max_length: int = 500) -> str | None:
    """Flatten an HTML or plain metadata value into one safe display line."""

    if not value:
        return None
    raw = str(value)
    decoded = html_to_text(raw) if "<" in raw else unescape_all(raw)
    text = " ".join(decoded.split())
    if not text or len(text) > max_length:
        return None
    return text


def clean_byline(value: str | None, *, max_length: int = 200) -> str | None:
    """Return a plausible writer name and reject email addresses or URLs."""

    text = clean_meta_text(value, max_length=max_length)
    if not text:
        return None
    text = re.sub(r"^(?:by|written by)\s+", "", text, flags=re.IGNORECASE)
    if not text or "://" in text:
        return None
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
        return None
    return text


def safe_image_url(value: str | None, *, base_url: str | None = None) -> str | None:
    """Return an absolute remote image URL, or ``None`` for anything else."""

    raw = str(value or "").strip()
    if not raw:
        return None
    if base_url:
        raw = urljoin(base_url, raw)
    parts = urlsplit(raw)
    if parts.scheme.lower() not in _IMAGE_SCHEMES or not parts.netloc:
        return None
    return raw


def is_promo_image(value: str | None) -> bool:
    """Return whether an image URL looks like site chrome rather than a cover."""

    if not value:
        return False
    return bool(_PROMO_IMAGE_TOKEN.search(urlsplit(value).path))


def _image_identity(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    parts = urlsplit(value)
    name = parts.path.rsplit("/", 1)[-1].lower()
    if not name:
        return None
    return (parts.hostname or "").lower(), name


def _same_image(left: str | None, right: str | None) -> bool:
    """Match the same file served at different sizes or CDN hostnames."""

    first = _image_identity(left)
    second = _image_identity(right)
    if first is None or second is None:
        return False
    if first == second:
        return True
    return first[1] == second[1] and len(first[1]) >= 16


def _figcaption_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    return clean_meta_text(node.get_text(" ", strip=True), max_length=1000)


def leading_image(value: str | None) -> tuple[str, str | None, str | None] | None:
    """Return the first image when it opens a sanitized article fragment.

    The tuple is ``(src, alt, caption)``. Only an image, an image-only
    paragraph, a linked image, or a figure may open the body; a fragment that
    starts with text is left alone.
    """

    if not value:
        return None

    soup = BeautifulSoup(value, "html.parser")
    for node in soup.contents:
        if isinstance(node, NavigableString):
            if str(node).strip():
                return None
            continue
        if not isinstance(node, Tag):
            continue

        caption = None
        image: Tag | None = None
        if node.name == "img":
            image = node
        elif node.name == "figure":
            image = node.find("img")
            caption = _figcaption_text(node.find("figcaption"))
        elif node.name in {"p", "a"}:
            if node.get_text(" ", strip=True):
                return None
            image = node.find("img")
        else:
            return None

        if image is None:
            return None
        src = safe_image_url(str(image.get("src") or ""))
        if src is None:
            return None
        return src, clean_meta_text(str(image.get("alt") or "")), caption
    return None


def strip_leading_image(
    value: str | None,
    image_url: str | None,
) -> tuple[str | None, str | None]:
    """Remove the body's opening image when it duplicates the cover.

    Returns the fragment and any caption that belonged to the removed figure.
    """

    if not value or not image_url:
        return value, None

    soup = BeautifulSoup(value, "html.parser")
    for node in soup.contents:
        if isinstance(node, NavigableString):
            if str(node).strip():
                return value, None
            continue
        if not isinstance(node, Tag):
            continue

        caption = None
        image: Tag | None = None
        if node.name == "img":
            image = node
        elif node.name == "figure":
            image = node.find("img")
            caption = _figcaption_text(node.find("figcaption"))
        elif node.name in {"p", "a"}:
            if node.get_text(" ", strip=True):
                return value, None
            image = node.find("img")
        else:
            return value, None

        if image is None or not _same_image(str(image.get("src") or ""), image_url):
            return value, None
        node.decompose()
        cleaned = str(soup).strip()
        return cleaned or None, caption
    return value, None


def image_alt_for(value: str | None, image_url: str | None) -> str | None:
    """Return the alt text of a matching image anywhere in a fragment."""

    if not value or not image_url:
        return None
    soup = BeautifulSoup(value, "html.parser")
    for image in soup.find_all("img"):
        if _same_image(str(image.get("src") or ""), image_url):
            return clean_meta_text(str(image.get("alt") or ""))
    return None


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

    Layout wrappers are first folded into paragraphs so div-based feeds keep
    their block structure after sanitizing. Relative links and image sources
    are resolved against ``base_url`` before the fragment is cleaned with nh3.
    Remote images keep only safe source and alt text attributes. Plain text and
    double-escaped markup produce ``None`` so the reader keeps rendering the
    plain-text summary instead.
    """

    if not value or not value.strip():
        return None

    soup = BeautifulSoup(value, "html.parser")
    if soup.find() is None:
        return None

    _normalize_structure(soup)

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
    if not cleaned:
        return None

    cleaned_soup = BeautifulSoup(cleaned, "html.parser")
    if cleaned_soup.find() is None:
        return None
    for paragraph in cleaned_soup.find_all("p"):
        if not paragraph.get_text(strip=True) and paragraph.find(["figure", "img"]) is None:
            paragraph.decompose()
    cleaned = str(cleaned_soup).strip()
    return cleaned or None


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
