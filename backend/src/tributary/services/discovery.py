from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .feeds import FeedFetchError, FeedParseError, download_url, normalize_url, parse_feed
from .text import readable_title
from .urls import UnsafeUrlError, normalize_input_url, validate_public_url

__all__ = ["DiscoveryResult", "FeedCandidate", "discover_feed"]

_DISCOVERY_ACCEPT = (
    "text/html,application/xhtml+xml,application/atom+xml,application/rss+xml,"
    "application/feed+json,application/xml;q=0.9,*/*;q=0.8"
)
_FEED_ACCEPT = (
    "application/atom+xml, application/rss+xml, application/feed+json, "
    "application/xml, text/xml, */*"
)
_FEED_TYPES = {
    "application/rss+xml": "rss",
    "application/atom+xml": "atom",
    "application/rdf+xml": "rdf",
    "application/feed+json": "json",
    "application/json": "json",
}
_COMMON_PATHS = (
    "/feed",
    "/rss",
    "/atom.xml",
    "/feed.xml",
    "/index.xml",
    "/?feed=rss2",
)
_MAX_CANDIDATES = 10
_MAX_PROBES = 6
_PROBE_SPACING = 0.25
_PROBE_BUDGET = 10.0


@dataclass(slots=True)
class FeedCandidate:
    url: str
    title: str = ""
    kind: str = "unknown"


@dataclass(slots=True)
class DiscoveryResult:
    input_url: str
    page_title: str | None = None
    candidates: list[FeedCandidate] = field(default_factory=list)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.monotonic()


def discover_feed(
    client: httpx.Client,
    url: str,
    *,
    max_probes: int = _MAX_PROBES,
    spacing: float = _PROBE_SPACING,
    budget: float = _PROBE_BUDGET,
) -> DiscoveryResult:
    """Find feed candidates at a URL, fetching the input exactly once."""

    input_url = normalize_input_url(url)
    validate_public_url(input_url)
    download = download_url(client, input_url, headers={"Accept": _DISCOVERY_ACCEPT})

    parsed = _try_parse(download.content)
    if parsed is not None:
        title = _feed_title(parsed) or _hostname(download.url)
        return DiscoveryResult(
            input_url=input_url,
            page_title=title,
            candidates=[
                FeedCandidate(
                    url=download.url,
                    title=title,
                    kind=_kind_for_version(parsed.get("version")),
                )
            ],
        )

    soup = BeautifulSoup(download.content, "html.parser")
    page_title = _page_title(soup)
    base_url = _base_url(soup, download.url)
    candidates = _link_candidates(soup, base_url, page_title)
    if candidates:
        return DiscoveryResult(input_url=input_url, page_title=page_title, candidates=candidates)

    candidate = _probe(
        client,
        _probe_urls(download.url, soup),
        max_probes=max_probes,
        spacing=spacing,
        budget=budget,
    )
    return DiscoveryResult(
        input_url=input_url,
        page_title=page_title,
        candidates=[candidate] if candidate is not None else [],
    )


def _try_parse(content: bytes):
    try:
        return parse_feed(content)
    except FeedParseError:
        return None


def _page_title(soup: BeautifulSoup) -> str | None:
    if soup.title is None:
        return None
    title = readable_title(soup.title.get_text(" ", strip=True)).strip()
    return title or None


def _base_url(soup: BeautifulSoup, response_url: str) -> str:
    base = soup.find("base", href=True)
    if base is None:
        return response_url
    candidate = normalize_url(urljoin(response_url, str(base.get("href") or "")))
    return candidate if _is_http(candidate) else response_url


def _link_candidates(
    soup: BeautifulSoup,
    base_url: str,
    page_title: str | None,
) -> list[FeedCandidate]:
    candidates: list[FeedCandidate] = []
    seen: set[str] = set()

    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        if isinstance(rel, str):
            rel = rel.split()
        if "alternate" not in {str(token).lower() for token in rel}:
            continue

        content_type = str(link.get("type") or "").split(";", 1)[0].strip().lower()
        kind = _FEED_TYPES.get(content_type)
        if kind is None:
            continue

        href = str(link.get("href") or "").strip()
        if not href:
            continue
        candidate_url = normalize_url(urljoin(base_url, href))
        if not _is_http(candidate_url) or candidate_url in seen:
            continue

        title = readable_title(str(link.get("title") or "")).strip()
        title = title or page_title or _hostname(candidate_url)
        candidates.append(FeedCandidate(url=candidate_url, title=title, kind=kind))
        seen.add(candidate_url)
        if len(candidates) >= _MAX_CANDIDATES:
            break

    return candidates


def _probe_urls(page_url: str, soup: BeautifulSoup) -> list[str]:
    parts = urlsplit(page_url)
    scheme = parts.scheme or "https"
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/")
    probes: list[str] = []

    if host.endswith(".substack.com"):
        probes.append(f"{scheme}://{host}/feed")

    if host == "reddit.com" or host.endswith(".reddit.com"):
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) >= 2 and segments[0] == "r":
            probes.append(f"https://{host}/r/{segments[1]}/.rss")

    if host == "github.com":
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) == 1:
            probes.append(f"https://github.com/{segments[0]}.atom")

    if path.startswith("/@"):
        probes.append(f"{scheme}://{host}{path}.rss")

    probes.extend(urljoin(page_url, common) for common in _COMMON_PATHS)

    unique: list[str] = []
    seen: set[str] = set()
    for probe in probes:
        normalized = normalize_url(probe)
        if normalized not in seen and _is_http(normalized):
            unique.append(normalized)
            seen.add(normalized)
    return unique


def _probe(
    client: httpx.Client,
    urls: list[str],
    *,
    max_probes: int,
    spacing: float,
    budget: float,
) -> FeedCandidate | None:
    started = _now()

    for index, probe_url in enumerate(urls[:max_probes]):
        if _now() - started >= budget:
            break
        if index:
            _sleep(spacing)
        if _now() - started >= budget:
            break

        try:
            download = download_url(client, probe_url, headers={"Accept": _FEED_ACCEPT})
            parsed = parse_feed(download.content)
        except (FeedFetchError, FeedParseError, UnsafeUrlError, httpx.HTTPError):
            continue

        title = _feed_title(parsed) or _hostname(download.url)
        return FeedCandidate(
            url=download.url,
            title=title,
            kind=_kind_for_version(parsed.get("version")),
        )

    return None


def _feed_title(parsed) -> str:
    return readable_title(str(parsed.feed.get("title") or "")).strip()


def _kind_for_version(version: object) -> str:
    value = str(version or "")
    if value.startswith("json"):
        return "json"
    if value.startswith("atom"):
        return "atom"
    if "rdf" in value:
        return "rdf"
    if value.startswith("rss"):
        return "rss"
    return "unknown"


def _hostname(url: str) -> str:
    return urlsplit(url).hostname or url


def _is_http(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)
