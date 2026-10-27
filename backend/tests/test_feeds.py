from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tributary.config import Settings
from tributary.models import Feed, Item
from tributary.services.feeds import fetch_feed, make_client, normalize_url, refresh_feeds

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com/</link>
    <description>An example feed</description>
    <item>
      <title>First post</title>
      <link>https://example.com/posts/first#comments</link>
      <guid isPermaLink="false">post-1</guid>
      <pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[<p>First body.</p>]]></description>
    </item>
    <item>
      <title>Second post</title>
      <link>https://example.com/posts/second</link>
      <description>Second body.</description>
    </item>
  </channel>
</rss>
"""


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_make_client_sets_identity(settings: Settings) -> None:
    with make_client(settings) as client:
        assert client.headers["user-agent"] == settings.user_agent
        assert client.follow_redirects is True


def test_normalize_url_removes_fragments_and_lowercases_the_host() -> None:
    assert (
        normalize_url(" HTTPS://Example.COM/Path?q=1#fragment ")
        == "https://example.com/Path?q=1"
    )


def test_fetch_feed_stores_feed_and_items(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=RSS.encode(),
            headers={
                "ETag": '"v1"',
                "Last-Modified": "Tue, 27 Oct 2026 10:00:00 GMT",
            },
        )

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://Example.com/feed.xml", client=client)
        db_session.commit()

    assert result.ok
    assert result.new_items == 2
    assert result.total_entries == 2

    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.url == "https://example.com/feed.xml"
    assert feed.title == "Example Feed"
    assert feed.etag == '"v1"'
    assert feed.last_modified == "Tue, 27 Oct 2026 10:00:00 GMT"
    assert feed.last_error is None
    assert feed.last_fetched is not None

    items = db_session.scalars(select(Item).order_by(Item.id)).all()
    assert [item.title for item in items] == ["First post", "Second post"]
    assert items[0].guid == "post-1"
    assert items[0].link == "https://example.com/posts/first"
    assert items[0].published == datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
    assert items[0].content == "<p>First body.</p>"
    assert items[1].guid == "https://example.com/posts/second"


def test_fetch_feed_does_not_duplicate_items(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    with mock_client(handler) as client:
        first = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()
        second = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert first.new_items == 2
    assert second.new_items == 0
    assert db_session.scalar(select(func.count()).select_from(Item)) == 2


def test_fetch_feed_sends_conditional_headers_and_handles_304(
    settings: Settings, db_session: Session
) -> None:
    seen_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        if len(seen_headers) == 1:
            return httpx.Response(
                200,
                content=RSS.encode(),
                headers={"ETag": '"v1"', "Last-Modified": "Tue, 27 Oct 2026 10:00:00 GMT"},
            )
        return httpx.Response(304, headers={"ETag": '"v2"'})

    with mock_client(handler) as client:
        first = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()
        second = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert first.new_items == 2
    assert second.not_modified is True
    assert second.new_items == 0
    assert seen_headers[1]["if-none-match"] == '"v1"'
    assert seen_headers[1]["if-modified-since"] == "Tue, 27 Oct 2026 10:00:00 GMT"

    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.etag == '"v2"'
    assert db_session.scalar(select(func.count()).select_from(Item)) == 2


def test_feed_html_is_cleaned_before_storage(
    settings: Settings, db_session: Session
) -> None:
    paragraph = (
        "<p>This is a sentence about a topic. It contains enough words to look "
        "like prose. Another sentence follows it here.</p>"
    )
    long_html = f"<div>{paragraph * 3}</div>"
    rss = f"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><title>Clean Feed</title>
      <item><title>Long post</title><link>https://example.com/long</link>
      <guid>long</guid><description><![CDATA[{long_html}]]></description></item>
    </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss.encode())

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/clean.xml", client=client)
        db_session.commit()

    assert result.new_items == 1
    item = db_session.scalar(select(Item))
    assert item is not None
    assert "This is a sentence about a topic" in item.content
    assert "<" not in item.content


def test_fetch_feed_records_http_errors(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/missing.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.error is not None
    assert "HTTPStatusError" in result.error

    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.last_error == result.error
    assert feed.last_fetched is not None
    assert db_session.scalar(select(func.count()).select_from(Item)) == 0


def test_fetch_feed_records_unparseable_feeds(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"this is not a feed")

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/broken.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.error is not None
    assert "SAXParseException" in result.error or "feed" in result.error.lower()


def test_refresh_continues_after_a_dead_feed(
    settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        session.add_all(
            [
                Feed(url="https://example.com/good.xml", title="Good"),
                Feed(url="https://example.com/bad.xml", title="Bad"),
            ]
        )
        session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("bad.xml"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, content=RSS.encode())

    with mock_client(handler) as client:
        results = refresh_feeds(session_factory, settings, client=client)

    assert len(results) == 2
    good = next(result for result in results if result.url.endswith("good.xml"))
    bad = next(result for result in results if result.url.endswith("bad.xml"))
    assert good.ok is True
    assert good.new_items == 2
    assert bad.ok is False
    assert bad.error is not None

    with session_factory() as session:
        feeds = {feed.url: feed for feed in session.scalars(select(Feed)).all()}
        assert feeds["https://example.com/good.xml"].last_error is None
        assert feeds["https://example.com/bad.xml"].last_error is not None
        assert session.scalar(select(func.count()).select_from(Item)) == 2


def test_refresh_without_feeds_returns_an_empty_list(
    settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    assert refresh_feeds(session_factory, settings) == []
