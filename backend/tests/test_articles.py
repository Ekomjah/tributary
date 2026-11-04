from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from tributary.config import Settings
from tributary.db import ensure_local_user
from tributary.models import Feed, Item
from tributary.services import articles


def make_item(
    session: Session,
    *,
    content: str = "",
    content_full: str | None = None,
    link: str | None = "https://example.com/post",
    title: str = "Post",
) -> Item:
    feed = Feed(
        owner_id=ensure_local_user(session).id,
        url="https://example.com/feed.xml",
        title="Example",
    )
    session.add(feed)
    session.flush()
    item = Item(
        feed_id=feed.id,
        guid="post-1",
        title=title,
        link=link,
        content=content,
        content_full=content_full,
    )
    session.add(item)
    session.commit()
    return item


def article_html() -> str:
    paragraph = "This is a substantial sentence about the article topic. " * 12
    return (
        "<html><body><nav>Menu</nav><article><h1>Example</h1>"
        + "".join(f"<p>{paragraph}</p>" for _ in range(3))
        + '<p>Read <a href="/about">about the project</a>.</p>'
        + "<h2>Section</h2><ul><li>First point</li><li>Second point</li></ul>"
        '<img src="/pic.jpg" alt="Pic"><blockquote>Quoted text.</blockquote>'
        "<table><tr><th>Column</th></tr><tr><td>Cell</td></tr></table>"
        "</article><footer>Footer</footer></body></html>"
    )


def test_feed_content_shortcut_skips_network(db_session: Session, settings: Settings) -> None:
    body = "A complete article from the feed. " * 30
    item = make_item(db_session, content=body, content_full=body)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the article page should not be fetched")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.fetched is False
    assert item.content_full == body.strip()
    assert item.fetch_status == "ok"
    assert item.content_fetched_at is not None


def test_long_description_triggers_article_fetch(db_session: Session, settings: Settings) -> None:
    description = "A long description from the feed. " * 30
    item = make_item(db_session, content=description)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert calls == 1
    assert result.fetched is True
    assert "substantial sentence" in (item.content_full or "")


def test_page_extraction_stores_readable_text(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="Short feed summary.")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.fetched is True
    assert item.fetch_status == "ok"
    assert "substantial sentence" in (item.content_full or "")
    assert "Menu" not in (item.content_full or "")


def test_successful_article_fetch_keeps_extracted_html(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short feed summary.")
    item.content_html = "<p>Short feed summary.</p>"
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert item.content_full
    assert item.content_html is not None
    assert "<p>" in item.content_html
    assert "<h2>Section</h2>" in item.content_html
    assert "<ul>" in item.content_html
    assert "<blockquote>" in item.content_html
    assert 'src="https://example.com/pic.jpg"' in item.content_html
    assert 'href="https://example.com/about"' in item.content_html
    assert "<table>" in item.content_html
    assert "<td>Cell</td>" in item.content_html
    assert "Menu" not in item.content_html
    assert "Footer" not in item.content_html
    assert "<script" not in item.content_html
    assert "<h1>" not in item.content_html


def test_article_fetch_drops_the_title_repeated_by_the_page(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short feed summary.", title="Example")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert item.content_html is not None
    assert "Example" not in item.content_html
    assert not (item.content_full or "").startswith("Example")


def frontmatter_article_html(*, lead_image: bool = True) -> str:
    paragraph = "A substantial sentence about the article topic. " * 12
    image = (
        '<figure><img src="/ace/standard/1920/abc123.jpg" alt="A wide cover">'
        "<figcaption>The cover caption.</figcaption></figure>"
        if lead_image
        else ""
    )
    return (
        "<html><head><title>Example</title>"
        '<meta name="author" content="Jane Doe">'
        '<meta property="og:image" content="https://example.com/ace/branded_news/1200/abc123.jpg">'
        "</head><body><article>"
        + image
        + "<ul><li>Published1 day ago</li></ul>"
        + "".join(f"<p>{paragraph}</p>" for _ in range(3))
        + "</article></body></html>"
    )


def test_article_fetch_moves_the_lead_image_into_frontmatter(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short feed summary.")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=frontmatter_article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert item.author == "Jane Doe"
    assert item.cover_image == "https://example.com/ace/standard/1920/abc123.jpg"
    assert item.cover_image_alt == "A wide cover"
    assert item.content_html is not None
    assert "abc123.jpg" not in item.content_html
    assert "<figcaption>" not in item.content_html
    assert "Published" not in item.content_html
    assert "substantial sentence" in item.content_html


def test_article_fetch_uses_page_metadata_when_the_body_has_no_lead_image(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short feed summary.")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=frontmatter_article_html(lead_image=False).encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert item.author == "Jane Doe"
    assert item.cover_image == "https://example.com/ace/branded_news/1200/abc123.jpg"
    assert item.cover_image_alt is None
    assert item.cover_caption is None


def test_article_fetch_keeps_frontmatter_when_metadata_is_missing_or_promotional(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short feed summary.")
    item.author = "Feed Author"
    item.cover_image = "https://example.com/feed-cover.jpg"
    item.cover_image_alt = "Feed cover"
    db_session.commit()

    paragraph = "A substantial sentence about the article topic. " * 12
    page = (
        "<html><head><title>Example</title>"
        '<meta property="og:image" content="https://example.com/newsletter/cover.jpg">'
        "</head><body><article>"
        + "".join(f"<p>{paragraph}</p>" for _ in range(3))
        + "</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert item.author == "Feed Author"
    assert item.cover_image == "https://example.com/feed-cover.jpg"
    assert item.cover_image_alt == "Feed cover"


def test_backfill_frontmatter_fills_old_items_without_touching_text(
    db_session: Session, settings: Settings
) -> None:
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item = make_item(db_session, content="Short feed summary.", content_full="Old full text.")
    item.fetch_status = "ok"
    item.content_fetched_at = fetched_at
    db_session.commit()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=frontmatter_article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        updated = articles.backfill_frontmatter(
            db_session,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert calls == 1
    assert updated == 1
    assert item.author == "Jane Doe"
    assert item.cover_image == "https://example.com/ace/standard/1920/abc123.jpg"
    assert item.content_html is not None
    assert "abc123.jpg" not in item.content_html
    assert item.content_full == "Old full text."
    assert item.fetch_status == "ok"
    assert item.content_fetched_at == fetched_at


def test_backfill_frontmatter_strips_a_cover_from_stored_html(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short feed summary.", content_full="Existing body.")
    item.fetch_status = "ok"
    item.content_html = (
        '<figure><img src="https://example.com/ace/standard/1920/abc123.jpg" alt="Old">'
        "<figcaption>Stored caption.</figcaption></figure><p>Existing body.</p>"
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=frontmatter_article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        updated = articles.backfill_frontmatter(
            db_session,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert updated == 1
    assert item.cover_image == "https://example.com/ace/standard/1920/abc123.jpg"
    assert item.cover_caption == "Stored caption."
    assert item.content_html == "<p>Existing body.</p>"
    assert item.content_full == "Existing body."


def test_backfill_frontmatter_leaves_failed_items_untouched(
    db_session: Session, settings: Settings
) -> None:
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item = make_item(db_session, content="Short feed summary.", content_full="Old full text.")
    item.fetch_status = "ok"
    item.content_fetched_at = fetched_at
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        updated = articles.backfill_frontmatter(
            db_session,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert updated == 0
    assert item.author is None
    assert item.cover_image is None
    assert item.content_full == "Old full text."
    assert item.fetch_status == "ok"
    assert item.content_fetched_at == fetched_at


def test_backfill_frontmatter_skips_items_that_already_have_it(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short feed summary.", content_full="Old full text.")
    item.fetch_status = "ok"
    item.author = "Existing Author"
    item.cover_image = "https://example.com/existing.jpg"
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("complete items should not be fetched")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        updated = articles.backfill_frontmatter(
            db_session,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert updated == 0
    assert item.author == "Existing Author"
    assert item.cover_image == "https://example.com/existing.jpg"


def test_short_page_is_empty(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body><p>Too short.</p></body></html>",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "empty"
    assert item.fetch_status == "empty"
    assert item.content_full is None
    assert item.content_fetched_at is not None


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "blocked"), (403, "blocked"), (429, "error"), (500, "error")],
)
def test_http_failures_are_recorded(
    db_session: Session,
    settings: Settings,
    status_code: int,
    expected: str,
) -> None:
    item = make_item(db_session, content="")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == expected
    assert item.fetch_status == expected
    assert item.content_full is None


def test_second_call_is_served_from_the_item(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=article_html().encode(),
        )

    active_settings = settings.model_copy(update={"article_delay_seconds": 0})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = articles.fetch_article(db_session, item, settings=active_settings, client=client)
        second = articles.fetch_article(db_session, item, settings=active_settings, client=client)

    assert first.status == "ok"
    assert second.status == "ok"
    assert second.fetched is False
    assert calls == 1


def test_force_refetches_even_after_success(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=article_html().encode(),
            )
        return httpx.Response(403)

    active_settings = settings.model_copy(update={"article_delay_seconds": 0})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        articles.fetch_article(db_session, item, settings=active_settings, client=client)
        result = articles.fetch_article(
            db_session,
            item,
            settings=active_settings,
            client=client,
            force=True,
        )

    assert calls == 2
    assert result.status == "blocked"
    assert item.fetch_status == "blocked"
    # A failed forced retry does not throw away text that was already stored.
    assert item.content_full is not None


def test_item_without_link_is_empty(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="", link=None)

    result = articles.fetch_article(db_session, item, settings=settings)

    assert result.status == "empty"
    assert item.fetch_status == "empty"
    assert item.content_fetched_at is not None


def test_page_size_is_capped(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="")
    body = article_html().encode() + b"x" * 10_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=body,
        )

    active_settings = settings.model_copy(
        update={"article_delay_seconds": 0, "article_max_bytes": 1_000}
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(db_session, item, settings=active_settings, client=client)

    assert result.bytes_read <= 1_000
    assert result.truncated is True


def test_domain_delay_sleeps_between_requests(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(articles.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(articles.time, "sleep", sleeps.append)
    monkeypatch.setitem(articles._DOMAIN_LAST, "example.com", 99.5)

    articles._wait_for_domain("example.com", 1.0)

    assert sleeps == [pytest.approx(0.5)]


def test_domain_delay_does_not_sleep_when_enough_time_passed(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(articles.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(articles.time, "sleep", sleeps.append)
    monkeypatch.setitem(articles._DOMAIN_LAST, "example.com", 90.0)

    articles._wait_for_domain("example.com", 1.0)

    assert sleeps == []


def test_article_client_does_not_follow_redirects(settings: Settings) -> None:
    with articles.make_client(settings) as client:
        assert client.follow_redirects is False


def test_domain_delay_applies_to_each_redirect_hop(
    db_session: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_item(db_session, content="", link="https://first.example/post")
    waits: list[str] = []

    def fake_wait(host: str, delay: float) -> None:
        waits.append(host)

    monkeypatch.setattr(articles, "_wait_for_domain", fake_wait)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.example":
            return httpx.Response(302, headers={"Location": "https://second.example/post"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 1.0}),
            client=client,
        )

    assert result.status == "ok"
    assert waits == ["first.example", "second.example"]


def test_article_fetch_uses_raw_bytes_for_windows_1252(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="Short summary.")
    paragraph = "It\u2019s caf\u00e9 \u2014 a substantial sentence about the article topic. " * 12
    page = (
        '<html><head><meta charset="windows-1252"></head><body><article>'
        + "".join(f"<p>{paragraph}</p>" for _ in range(3))
        + "</article></body></html>"
    ).encode("windows-1252")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert "caf\u00e9" in (item.content_full or "")
    assert "\u00e2\u20ac\u2122" not in (item.content_full or "")


def test_article_fetch_rejects_private_url(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="", link="http://127.0.0.1/secret")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"<html></html>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert calls == 0
    assert result.status == "error"
    assert item.fetch_status == "error"


def test_article_fetch_refuses_redirect_to_private_address(
    db_session: Session, settings: Settings
) -> None:
    item = make_item(db_session, content="", link="https://example.com/post")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert requests == ["https://example.com/post"]
    assert result.status == "error"
    assert item.fetch_status == "error"


CHALLENGE_PAGE = b"""
<html><head><title>Reddit</title></head><body>
  <form action="/r/technology/comments/abc/post/">
    <input name="solution" type="hidden">
    <input name="js_challenge" type="hidden" value="1">
    <input name="jsc_token" type="hidden" value="abc">
  </form>
</body></html>
"""


def test_js_challenge_is_blocked_without_running_extraction(
    db_session: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = make_item(db_session, content="")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=CHALLENGE_PAGE,
        )

    def fail_extract(*args, **kwargs):  # pragma: no cover
        raise AssertionError("challenge pages must not reach trafilatura")

    monkeypatch.setattr(articles.trafilatura, "extract", fail_extract)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "blocked"
    assert result.reason == "js_challenge"
    assert item.fetch_status == "blocked"
    assert item.content_full is None


def test_json_ld_article_body_is_used_when_visible_text_is_short(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    body = "A complete article body from structured data. " * 20
    page = (
        "<html><head>"
        '<script type="application/ld+json">'
        + '{"@type": "NewsArticle", "articleBody": "'
        + body.replace('"', '\\"')
        + '"}'
        + "</script></head><body><p>Too short.</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.reason == "structured_data"
    assert "structured data" in (item.content_full or "")


def test_meta_description_is_used_when_the_page_has_no_article(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    description = "A substantial summary published in the page metadata. " * 12
    page = (
        "<html><head>"
        f'<meta name="description" content="{description}">'
        "</head><body><p>Too short.</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.reason == "meta_description"
    assert "published in the page metadata" in (item.content_full or "")


def test_pdf_response_is_recorded_with_a_reason(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.7",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "empty"
    assert result.reason == "pdf"
    assert item.fetch_status == "empty"


def test_long_feed_description_can_be_trusted_opt_in(
    db_session: Session,
    settings: Settings,
) -> None:
    description = "A long description from the feed. " * 30
    item = make_item(db_session, content=description)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the trusted feed body should skip the network")

    active = settings.model_copy(
        update={
            "article_delay_seconds": 0,
            "article_trust_long_description": True,
        }
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=active,
            client=client,
        )

    assert result.status == "ok"
    assert result.reason == "feed_fallback"
    assert result.fetched is False
    assert item.content_full == description.strip()


REDDIT_CHALLENGE = CHALLENGE_PAGE

REDDIT_LINK_RSS = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Reddit thread</title>
  <entry>
    <id>t3_abc</id>
    <title>Reddit thread</title>
    <link href="https://www.reddit.com/r/technology/comments/abc/post/" />
    <content type="html"><![CDATA[
      <table><tr><td>
        <a href="https://www.reddit.com/r/technology/comments/abc/post/"><img src="https://preview.redd.it/a.jpg"></a>
        submitted by <a href="https://www.reddit.com/user/someone">/u/someone</a>
        <a href="https://example.com/story">[link]</a>
        <a href="https://www.reddit.com/r/technology/comments/abc/post/">[comments]</a>
      </td></tr></table>
    ]]></content>
  </entry>
</feed>
"""

REDDIT_SELF_RSS = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Reddit self post</title>
  <entry>
    <id>t3_abc</id>
    <title>Reddit self post</title>
    <link href="https://www.reddit.com/r/technology/comments/abc/post/" />
    <content type="html"><![CDATA[
      <div class="md"><p>This is the complete text of a Reddit self post.</p></div>
    ]]></content>
  </entry>
</feed>
"""


def test_reddit_recovery_follows_one_external_link(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(
        db_session,
        content="",
        link="https://www.reddit.com/r/technology/comments/abc/post/",
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path.endswith("/.rss"):
            return httpx.Response(
                200,
                headers={"content-type": "application/atom+xml"},
                content=REDDIT_LINK_RSS.encode(),
            )
        if request.url.host == "www.reddit.com":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=REDDIT_CHALLENGE,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=article_html().encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.reason == "reddit_link"
    assert "substantial sentence" in (item.content_full or "")
    assert any(url.endswith("/.rss") for url in requests)
    assert "https://example.com/story" in requests


def test_reddit_recovery_uses_the_self_post_body(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(
        db_session,
        content="",
        link="https://www.reddit.com/r/technology/comments/abc/post/",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.rss"):
            return httpx.Response(
                200,
                headers={"content-type": "application/atom+xml"},
                content=REDDIT_SELF_RSS.encode(),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=REDDIT_CHALLENGE,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.reason == "reddit_self"
    assert "complete text of a Reddit self post" in (item.content_full or "")
    assert "submitted by" not in (item.content_full or "")


def test_reddit_link_post_without_body_stays_empty(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(
        db_session,
        content="",
        link="https://www.reddit.com/r/technology/comments/abc/post/",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.rss"):
            return httpx.Response(
                200,
                headers={"content-type": "application/atom+xml"},
                content=REDDIT_LINK_RSS.encode(),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=REDDIT_CHALLENGE,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    # The external link resolves to the challenge page in this mock, so there
    # is no body to keep and the reader must not show Reddit boilerplate.
    assert result.status == "blocked"
    assert item.content_full is None


def long_paragraphs(label: str = "Body", count: int = 3) -> list[str]:
    return [
        f"{label} paragraph {index} explains the topic with enough detail to read like real prose, "
        "including context, a caveat and a concrete example. " * 4
        for index in range(count)
    ]


def test_div_based_page_keeps_every_article_paragraph(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="Short feed summary.")
    paragraphs = long_paragraphs("Div")
    page = (
        "<html><body><nav>Menu</nav><main><div class='article-body'>"
        + "".join(f"<div>{paragraph}</div>" for paragraph in paragraphs)
        + "</div></main><footer>Footer</footer></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    for index in range(3):
        assert f"Div paragraph {index}" in (item.content_full or "")
    assert "Menu" not in (item.content_full or "")
    assert "Footer" not in (item.content_full or "")


def test_github_style_readme_is_kept_without_the_sidebar(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="Short feed summary.", title="README")
    readme = "".join(
        f"<p>Step {index} installs the package and explains the option with enough words.</p>"
        for index in range(6)
    )
    page = (
        "<html><body><nav>Menu</nav><div class='sidebar'>Sidebar links</div>"
        f"<article id='readme' class='markdown-body'><h1>README</h1>{readme}"
        "<pre>pip install tributary</pre></article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert "Step 5" in (item.content_full or "")
    assert "pip install tributary" in (item.content_full or "")
    assert "Sidebar" not in (item.content_full or "")
    assert "Menu" not in (item.content_full or "")


def test_next_data_state_is_read_when_visible_html_is_empty(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    content = "".join(
        f"<p>State paragraph {index} carries the article body out of the bootstrap payload "
        "with enough detail to be worth reading. </p>"
        for index in range(5)
    )
    payload = json.dumps({"props": {"pageProps": {"article": {"content": content}}}})
    page = (
        "<html><body><div id='root'></div>"
        f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'
        "</body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.reason == "embedded_state"
    for index in range(5):
        assert f"State paragraph {index}" in (item.content_full or "")
    assert "<p>" in (item.content_html or "")


def test_short_article_with_og_type_is_kept(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    note = "A short but genuine note about a fix that shipped today, with context. " * 4
    page = (
        "<html><head><meta property='og:type' content='article'></head>"
        f"<body><article><p>{note}</p></article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert "genuine note" in (item.content_full or "")


def test_short_page_without_article_signals_stays_empty(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    note = "A short note that never declares itself an article. " * 6
    page = f"<html><body><div>{note}</div></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "empty"
    assert item.content_full is None


def test_json_ld_graph_body_is_used(db_session: Session, settings: Settings) -> None:
    item = make_item(db_session, content="")
    body = "A complete article body from a graph node. " * 20
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [{"@type": "NewsArticle", "articleBody": body}],
        }
    )
    page = (
        "<html><head>"
        f'<script type="application/ld+json">{payload}</script>'
        "</head><body><p>Too short.</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert result.reason == "structured_data"
    assert "graph node" in (item.content_full or "")


def test_table_cells_survive_in_plain_text(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    paragraphs = long_paragraphs("Table")
    page = (
        "<html><body><article>"
        + "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        + "<table><tr><th>Name</th><th>Value</th></tr>"
        "<tr><td>Alpha</td><td>Cell</td></tr></table>"
        "</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert "Cell" in (item.content_full or "")
    assert "<table>" in (item.content_html or "")


def test_paywall_phrase_inside_a_script_does_not_block_a_short_article(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    note = "A short but genuine note about a fix that shipped today, with context. " * 4
    page = (
        "<html><head><meta property='og:type' content='article'></head><body>"
        "<script>var copy = 'subscribe to continue reading';</script>"
        f"<article><p>{note}</p></article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "ok"
    assert "genuine note" in (item.content_full or "")


def test_container_candidate_skips_an_empty_article_wrapper() -> None:
    paragraphs = long_paragraphs("Main", count=3)
    page = (
        "<html><body><article><h1>Title</h1></article><main>"
        + "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        + "</main></body></html>"
    )

    candidate = articles._candidate_containers(page.encode(), "https://example.com/post")

    assert candidate is not None
    assert "Main paragraph 0" in candidate.text
    assert "Main paragraph 2" in candidate.text


def test_paywall_page_is_blocked_before_using_its_meta_description(
    db_session: Session,
    settings: Settings,
) -> None:
    item = make_item(db_session, content="")
    description = "A substantial summary published in the page metadata. " * 12
    page = (
        "<html><head>"
        f'<meta name="description" content="{description}">'
        "</head><body><article><h1>Members only</h1>"
        "<p>Subscribe to continue reading this story.</p>"
        "</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page.encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = articles.fetch_article(
            db_session,
            item,
            settings=settings.model_copy(update={"article_delay_seconds": 0}),
            client=client,
        )

    assert result.status == "blocked"
    assert result.reason == "paywall"
    assert item.content_full is None
