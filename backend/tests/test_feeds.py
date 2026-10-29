from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tributary.config import Settings
from tributary.models import Feed, Item
from tributary.services import feeds
from tributary.services.feeds import (
    fetch_feed,
    make_client,
    normalize_url,
    parse_feed,
    refresh_feeds,
)

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


JSON_TEXT = "A JSON Feed article sentence. " * 30
JSON_HTML = f"<p>{JSON_TEXT}</p>"
JSON_FEED = f"""{{
  "version": "https://jsonfeed.org/version/1.1",
  "title": "JSON Feed",
  "home_page_url": "https://example.com/",
  "items": [
    {{
      "id": "json-1",
      "url": "https://example.com/posts/json-1",
      "title": "JSON text post",
      "content_text": "{JSON_TEXT}"
    }},
    {{
      "id": "json-2",
      "url": "https://example.com/posts/json-2",
      "title": "JSON HTML post",
      "content_html": "{JSON_HTML}"
    }}
  ]
}}"""


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_make_client_sets_identity(settings: Settings) -> None:
    with make_client(settings) as client:
        assert client.headers["user-agent"] == settings.user_agent
        assert client.follow_redirects is False


def test_normalize_url_removes_fragments_and_lowercases_the_host() -> None:
    assert (
        normalize_url(" HTTPS://Example.COM/Path?q=1#fragment ") == "https://example.com/Path?q=1"
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
    assert items[0].content == "First body."
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


def test_feed_html_is_cleaned_before_storage(settings: Settings, db_session: Session) -> None:
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
    assert item.content_full is None
    assert item.fetch_status is None
    assert item.content_html is not None
    assert item.content_html.startswith("<p>")
    assert "<div>" not in item.content_html


def test_feed_stores_sanitized_content_html(
    settings: Settings, db_session: Session
) -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel><title>HTML Feed</title>
        <item><title>HTML post</title><link>https://example.com/post</link>
        <guid>html-post</guid>
        <content:encoded><![CDATA[
          <p onclick="steal()">Hello <script>alert(1)</script>
          <img src="/photo.jpg" alt="Photo" onerror="steal()">
          <a href="/more">more</a></p>
        ]]></content:encoded></item>
      </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss.encode())

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/html.xml", client=client)
        db_session.commit()

    item = db_session.scalar(select(Item))
    assert item is not None
    assert item.content_html is not None
    assert "<script" not in item.content_html
    assert "onclick" not in item.content_html
    assert "onerror" not in item.content_html
    assert 'src="https://example.com/photo.jpg"' in item.content_html
    assert 'alt="Photo"' in item.content_html
    assert 'href="https://example.com/more"' in item.content_html
    assert "Hello" in item.content


def test_feed_uses_entry_images_when_content_has_none(
    settings: Settings, db_session: Session
) -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
      <channel><title>Image Feed</title>
        <item><title>Enclosure post</title><link>https://example.com/enclosure</link>
        <guid>enclosure</guid><description><![CDATA[<p>Enclosure body.</p>]]></description>
        <enclosure url="https://cdn.example.com/enclosure.jpg" type="image/jpeg" length="123"/>
        </item>
        <item><title>Thumbnail post</title><link>https://example.com/thumbnail</link>
        <guid>thumbnail</guid><description><![CDATA[<p>Thumbnail body.</p>]]></description>
        <media:thumbnail url="https://cdn.example.com/thumbnail.jpg"/>
        </item>
        <item><title>Audio post</title><link>https://example.com/audio</link>
        <guid>audio</guid><description><![CDATA[<p>Audio body.</p>]]></description>
        <enclosure url="https://cdn.example.com/episode.mp3" type="audio/mpeg" length="123"/>
        </item>
      </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss.encode())

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/images.xml", client=client)
        db_session.commit()

    items = list(db_session.scalars(select(Item).order_by(Item.id)).all())
    assert len(items) == 3
    assert items[0].cover_image == "https://cdn.example.com/enclosure.jpg"
    assert items[0].content_html == "<p>Enclosure body.</p>"
    assert items[1].cover_image == "https://cdn.example.com/thumbnail.jpg"
    assert items[1].content_html == "<p>Thumbnail body.</p>"
    assert items[2].cover_image is None
    assert items[2].content_html == "<p>Audio body.</p>"


def test_fetch_json_feed_uses_item_image_as_lead_image(
    settings: Settings, db_session: Session
) -> None:
    payload = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "JSON Image Feed",
        "items": [
            {
                "id": "json-image",
                "url": "https://example.com/posts/json-image",
                "title": "JSON image post",
                "content_html": "<p>JSON body.</p>",
                "image": "https://cdn.example.com/json.jpg",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/feed+json"},
            content=json.dumps(payload).encode(),
        )

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/image.json", client=client)
        db_session.commit()

    item = db_session.scalar(select(Item))
    assert item is not None
    assert item.cover_image == "https://cdn.example.com/json.jpg"
    assert item.content_html == "<p>JSON body.</p>"


def test_feed_stores_lead_image_and_writer_as_frontmatter(
    settings: Settings, db_session: Session
) -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel><title>Frontmatter Feed</title>
        <item><title>Cover post</title><link>https://example.com/cover-post</link>
        <guid>cover-post</guid><author>Jane Doe</author>
        <content:encoded><![CDATA[
          <figure><img src="/cover.jpg" alt="A wide cover">
          <figcaption>The cover caption.</figcaption></figure>
          <p>The article body.</p>
        ]]></content:encoded></item>
      </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss.encode())

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/frontmatter.xml", client=client)
        db_session.commit()

    item = db_session.scalar(select(Item))
    assert item is not None
    assert item.author == "Jane Doe"
    assert item.cover_image == "https://example.com/cover.jpg"
    assert item.cover_image_alt == "A wide cover"
    assert item.cover_caption == "The cover caption."
    assert item.content_html == "<p>The article body.</p>"


def test_fetch_feed_records_http_errors(settings: Settings, db_session: Session) -> None:
    feed = Feed(url="https://example.com/missing.xml", title="Missing")
    db_session.add(feed)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/missing.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.error is not None
    assert "HTTPStatusError" in result.error

    assert feed.last_error == result.error
    assert feed.last_fetched is not None
    assert db_session.scalar(select(func.count()).select_from(Item)) == 0


def test_invalid_first_fetch_creates_no_feed_row(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/missing.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.feed_id is None
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0


def test_fetch_feed_records_unparseable_feeds(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"this is not a feed")

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/broken.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.error is not None
    assert "not a feed" in result.error.lower()
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0


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


EMPTY_RSS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<rss version="2.0"><channel><title>Empty Feed</title>'
    "<description>Nothing yet</description></channel></rss>"
)

RSS_RELATIVE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Relative Feed</title>
  <item><title>Relative post</title><link>posts/relative</link><guid>relative</guid>
  <description>Relative body.</description></item>
</channel></rss>
"""

LONG_BODY = "Full body sentence. " * 40
CONTENT_RSS = f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel><title>Content Feed</title>
    <item><title>Encoded post</title><link>https://example.com/encoded</link>
    <guid>encoded</guid><description>Short summary.</description>
    <content:encoded><![CDATA[<p>{LONG_BODY}</p>]]></content:encoded></item>
  </channel>
</rss>
"""


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (200, b""),
        (200, b"   \n"),
        (
            202,
            b"<?xml version='1.0'?><rss version='2.0'>"
            b"<channel><title>Later</title></channel></rss>",
        ),
        (204, b""),
    ],
)
def test_fetch_rejects_empty_or_non_ready_responses(
    settings: Settings,
    db_session: Session,
    status_code: int,
    body: bytes,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body)

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.error is not None
    assert "feed" in result.error.lower() or "empty" in result.error.lower()
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0


def test_fetch_rejects_html_without_a_feed(settings: Settings, db_session: Session) -> None:
    body = b"<!doctype html><html><head><title>Blog</title></head><body>Hello</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/blog", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.error is not None
    assert "not a feed" in result.error.lower()
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0


def test_fetch_accepts_a_valid_feed_with_zero_entries(
    settings: Settings, db_session: Session
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=EMPTY_RSS.encode())

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/empty.xml", client=client)
        db_session.commit()

    assert result.ok is True
    assert result.new_items == 0
    assert result.total_entries == 0

    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.title == "Empty Feed"
    assert feed.last_error is None


def test_invalid_response_keeps_existing_feed_metadata(
    settings: Settings, db_session: Session
) -> None:
    feed = Feed(
        url="https://example.com/feed.xml",
        title="Old title",
        etag='"v1"',
        last_modified="Tue, 27 Oct 2026 10:00:00 GMT",
    )
    db_session.add(feed)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body>Not a feed</body></html>")

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert feed.title == "Old title"
    assert feed.etag == '"v1"'
    assert feed.last_modified == "Tue, 27 Oct 2026 10:00:00 GMT"
    assert feed.last_error is not None


def test_fetch_feed_sets_content_full_only_for_content_encoded(
    settings: Settings, db_session: Session
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=CONTENT_RSS.encode())

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/content.xml", client=client)
        db_session.commit()

    assert result.new_items == 1
    item = db_session.scalar(select(Item))
    assert item is not None
    assert item.content == LONG_BODY.strip()
    assert item.content_full == LONG_BODY.strip()
    assert item.fetch_status == "ok"
    assert item.content_fetched_at is not None


def test_parse_json_feed() -> None:
    parsed = parse_feed(JSON_FEED.encode())

    assert parsed.version.startswith("json")
    assert parsed.feed.title == "JSON Feed"
    assert len(parsed.entries) == 2
    assert parsed.entries[0].title == "JSON text post"


def test_fetch_json_feed_stores_items(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/feed+json"},
            content=JSON_FEED.encode(),
        )

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/feed.json", client=client)
        db_session.commit()

    assert result.ok is True
    assert result.new_items == 2
    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.title == "JSON Feed"
    items = list(db_session.scalars(select(Item).order_by(Item.id)).all())
    assert [item.title for item in items] == ["JSON text post", "JSON HTML post"]
    assert items[0].content_full == JSON_TEXT.strip()
    assert items[1].content_full == JSON_TEXT.strip()
    assert "<p>" not in items[1].content
    assert items[0].content_html is None
    assert items[1].content_html is not None
    assert items[1].content_html.startswith("<p>")


def test_make_client_accepts_json_feed(settings: Settings) -> None:
    with make_client(settings) as client:
        assert "application/feed+json" in client.headers["accept"]


def test_feed_span_uses_only_the_host(
    settings: Settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    names: list[str] = []

    class Span:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def set_data(self, *args, **kwargs) -> None:
            pass

        def set_status(self, *args, **kwargs) -> None:
            pass

    def fake_start_span(*, op: str, name: str) -> Span:
        names.append(name)
        return Span()

    monkeypatch.setattr(feeds.sentry_sdk, "start_span", fake_start_span)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/feed.xml?token=secret", client=client)

    assert names == ["example.com"]


def test_format_error_redacts_url_credentials_and_query() -> None:
    error = feeds._format_error(
        RuntimeError("GET https://user:pass@example.com/feed?token=secret#frag failed")
    )

    assert "secret" not in error
    assert "user:pass" not in error
    assert "https://example.com/feed" in error


def test_fetch_feed_normalizes_entities_in_titles_and_summary(
    settings: Settings, db_session: Session
) -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><title>It&amp;#8217;s a blog</title>
      <item><title>It&amp;#8217;s a post</title><link>https://example.com/post</link>
      <guid>post</guid><description>Short &amp;#8217; summary</description></item>
    </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss.encode())

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/entities.xml", client=client)
        db_session.commit()

    feed = db_session.scalar(select(Feed))
    item = db_session.scalar(select(Item))
    assert feed is not None
    assert item is not None
    assert feed.title == "It\u2019s a blog"
    assert item.title == "It\u2019s a post"
    assert item.content == "Short \u2019 summary"


def test_feed_and_item_titles_strip_markup(
    settings: Settings, db_session: Session
) -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><title><![CDATA[<b>Markup</b> Feed]]></title>
      <item><title><![CDATA[<i>Post</i> title]]></title>
      <link>https://example.com/post</link><guid>markup</guid>
      <description>Short body.</description></item>
    </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss.encode())

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/markup.xml", client=client)
        db_session.commit()

    feed = db_session.scalar(select(Feed))
    item = db_session.scalar(select(Item))
    assert feed is not None
    assert item is not None
    assert feed.title == "Markup Feed"
    assert item.title == "Post title"


def test_fetch_preserves_validators_when_response_omits_them(
    settings: Settings, db_session: Session
) -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        if len(seen) == 1:
            return httpx.Response(
                200,
                content=RSS.encode(),
                headers={
                    "ETag": '"v1"',
                    "Last-Modified": "Tue, 27 Oct 2026 10:00:00 GMT",
                },
            )
        return httpx.Response(200, content=RSS.encode())

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()
        fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()
        fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.etag == '"v1"'
    assert feed.last_modified == "Tue, 27 Oct 2026 10:00:00 GMT"
    assert seen[2]["if-none-match"] == '"v1"'
    assert seen[2]["if-modified-since"] == "Tue, 27 Oct 2026 10:00:00 GMT"


def test_fetch_updates_validators_when_response_provides_new_ones(
    settings: Settings, db_session: Session
) -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        if len(seen) == 1:
            return httpx.Response(200, content=RSS.encode(), headers={"ETag": '"v1"'})
        return httpx.Response(200, content=RSS.encode(), headers={"ETag": '"v2"'})

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()
        fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.etag == '"v2"'


def test_fetch_preserves_validators_on_304_without_headers(
    settings: Settings, db_session: Session
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                content=RSS.encode(),
                headers={
                    "ETag": '"v1"',
                    "Last-Modified": "Tue, 27 Oct 2026 10:00:00 GMT",
                },
            )
        return httpx.Response(304)

    with mock_client(handler) as client:
        fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()
        result = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert result.not_modified is True
    feed = db_session.scalar(select(Feed))
    assert feed is not None
    assert feed.etag == '"v1"'
    assert feed.last_modified == "Tue, 27 Oct 2026 10:00:00 GMT"


def test_relative_entry_links_use_the_final_redirect_url(
    settings: Settings, db_session: Session
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old/feed":
            return httpx.Response(301, headers={"Location": "/new/feed"})
        return httpx.Response(200, content=RSS_RELATIVE.encode())

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/old/feed", client=client)
        db_session.commit()

    assert result.ok is True
    item = db_session.scalar(select(Item))
    assert item is not None
    assert item.link == "https://example.com/new/posts/relative"


def test_fetch_refuses_a_redirect_to_a_private_address(
    settings: Settings, db_session: Session
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=RSS.encode())

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert requests == ["https://example.com/feed.xml"]
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0


def test_fetch_refuses_a_redirect_with_credentials(settings: Settings, db_session: Session) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://user:pass@example.com/feed"},
        )

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert requests == ["https://example.com/feed.xml"]
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0


def test_fetch_rejects_url_credentials(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("a URL with credentials must not be requested")

    with mock_client(handler) as client:
        result = fetch_feed(
            db_session,
            "https://user:pass@example.com/feed.xml",
            client=client,
        )
        db_session.commit()

    assert result.ok is False
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0


def test_fetch_stops_after_too_many_redirects(settings: Settings, db_session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/loop"})

    with mock_client(handler) as client:
        result = fetch_feed(db_session, "https://example.com/feed.xml", client=client)
        db_session.commit()

    assert result.ok is False
    assert result.error is not None
    assert "redirect" in result.error.lower()
    assert db_session.scalar(select(func.count()).select_from(Feed)) == 0
