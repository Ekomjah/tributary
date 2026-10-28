from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import Session

from tributary.config import Settings
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
    feed = Feed(url="https://example.com/feed.xml", title="Example")
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
        + "</article><footer>Footer</footer></body></html>"
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


def test_successful_article_fetch_clears_display_html(
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
    assert item.content_html is None


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
