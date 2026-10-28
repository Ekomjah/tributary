from __future__ import annotations

import httpx
import pytest

from tributary.services import discovery
from tributary.services.urls import UnsafeUrlError

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Discovered Feed</title>
    <link>https://example.com/</link>
    <description>A discovered feed</description>
  </channel>
</rss>
"""

JSON_FEED = """{
  "version": "https://jsonfeed.org/version/1.1",
  "title": "JSON Feed",
  "home_page_url": "https://example.com/",
  "items": []
}
"""


def html_page(head: str = "", body: str = "") -> bytes:
    return (
        "<!doctype html><html><head><title>Example Blog</title>"
        f"{head}</head><body>{body}</body></html>"
    ).encode()


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_discover_finds_alternate_link_and_resolves_relative_href() -> None:
    page = html_page(
        '<link rel="alternate" type="application/rss+xml" '
        'title="Example Feed" href="/feed.xml">'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/blog"
        return httpx.Response(200, headers={"content-type": "text/html"}, content=page)

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/blog")

    assert result.input_url == "https://example.com/blog"
    assert result.page_title == "Example Blog"
    found = [(candidate.url, candidate.title, candidate.kind) for candidate in result.candidates]
    assert found == [("https://example.com/feed.xml", "Example Feed", "rss")]


def test_discover_honors_base_href() -> None:
    page = html_page(
        '<base href="https://cdn.example.com/blog/">'
        '<link rel="alternate" type="application/atom+xml" href="feed.xml">'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=page)

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/blog")

    assert result.candidates[0].url == "https://cdn.example.com/blog/feed.xml"
    assert result.candidates[0].title == "Example Blog"
    assert result.candidates[0].kind == "atom"


def test_discover_returns_multiple_candidates_deduped_and_capped() -> None:
    links = "".join(
        f'<link rel="alternate" type="application/rss+xml" title="Feed {index}" '
        f'href="/feed-{index}.xml">'
        for index in range(12)
    )
    links += '<link rel="alternate" type="application/rss+xml" href="/feed-0.xml">'
    page = html_page(links)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=page)

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/blog")

    assert len(result.candidates) == 10
    assert len({candidate.url for candidate in result.candidates}) == 10


def test_discover_returns_the_input_when_it_is_already_a_feed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/rss+xml"},
            content=RSS.encode(),
        )

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/feed.xml")

    assert len(result.candidates) == 1
    assert result.candidates[0].url == "https://example.com/feed.xml"
    assert result.candidates[0].title == "Discovered Feed"
    assert result.candidates[0].kind == "rss"


def test_discover_parses_a_json_feed_input() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/feed+json"},
            content=JSON_FEED.encode(),
        )

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/feed.json")

    assert len(result.candidates) == 1
    assert result.candidates[0].title == "JSON Feed"
    assert result.candidates[0].kind == "json"


def test_discover_reads_json_feed_links() -> None:
    page = html_page(
        '<link rel="alternate" type="application/feed+json" '
        'title="JSON Feed" href="/feed.json">'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=page)

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/blog")

    assert result.candidates[0].url == "https://example.com/feed.json"
    assert result.candidates[0].kind == "json"


def test_discover_uses_platform_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(discovery, "_sleep", sleeps.append)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=html_page(),
            )
        if request.url.path == "/feed":
            return httpx.Response(
                200,
                headers={"content-type": "application/rss+xml"},
                content=RSS.encode(),
            )
        return httpx.Response(404)

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.substack.com/")

    assert result.candidates[0].url == "https://example.substack.com/feed"
    assert sleeps == []


def test_discover_probes_common_paths_with_spacing_and_a_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(discovery, "_sleep", sleeps.append)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/blog":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=html_page(),
            )
        return httpx.Response(404)

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/blog")

    assert result.candidates == []
    assert len(requested) == 7  # the page plus at most six probes
    assert sleeps == [0.25] * 5


def test_discover_returns_no_candidates_for_a_plain_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "_sleep", lambda seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html_page())

    with mock_client(handler) as client:
        result = discovery.discover_feed(client, "https://example.com/blog")

    assert result.candidates == []


def test_discover_rejects_an_unsafe_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("an unsafe URL must not be requested")

    with mock_client(handler) as client:
        with pytest.raises(UnsafeUrlError):
            discovery.discover_feed(client, "http://127.0.0.1/feed")
