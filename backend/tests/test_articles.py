from __future__ import annotations

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
