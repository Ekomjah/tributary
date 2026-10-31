from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tributary.boxes import (
    PipeSpec,
    PipeSpecError,
    RunContext,
    load_pipe_spec,
    run_pipe,
)
from tributary.boxes.plain import (
    DedupeBox,
    FetchBox,
    FilterBox,
    FullTextBox,
    LimitBox,
    MergeBox,
    SortBox,
)
from tributary.config import Settings
from tributary.db import ensure_local_user
from tributary.models import Feed, Item
from tributary.schemas import ItemOut

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com/</link>
    <description>An example feed</description>
    <item>
      <title>First post</title>
      <link>https://example.com/posts/first#comments</link>
      <guid>post-1</guid>
      <pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>
      <description>First body.</description>
    </item>
  </channel>
</rss>
"""


def make_item(
    item_id: int,
    title: str,
    *,
    link: str | None = None,
    guid: str | None = None,
    published: datetime | None = None,
    content: str = "",
) -> ItemOut:
    return ItemOut(
        id=item_id,
        feed_id=1,
        guid=guid or f"guid-{item_id}",
        title=title,
        link=link,
        published=published,
        content=content,
        is_read=False,
        starred=False,
        fetched_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
        labels=[],
        summary=None,
    )


def test_pipe_spec_accepts_the_plain_boxes() -> None:
    spec = PipeSpec.model_validate(
        {
            "name": "Test",
            "steps": [
                {"box": "fetch", "urls": ["https://example.com/feed.xml"]},
                {"box": "merge"},
                {"box": "dedupe", "by": "link"},
                {"box": "filter", "keyword": "python"},
                {"box": "sort", "by": "published", "order": "desc"},
                {"box": "limit", "count": 5},
                {"box": "fulltext"},
            ],
        }
    )

    assert [step.box for step in spec.steps] == [
        "fetch",
        "merge",
        "dedupe",
        "filter",
        "sort",
        "limit",
        "fulltext",
    ]


def test_pipe_spec_rejects_unknown_boxes_and_empty_urls() -> None:
    with pytest.raises(ValidationError):
        PipeSpec.model_validate({"steps": [{"box": "unknown"}]})

    with pytest.raises(ValidationError):
        PipeSpec.model_validate({"steps": [{"box": "fetch", "urls": []}]})


def test_load_pipe_spec_reports_bad_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(PipeSpecError, match="Could not read"):
        load_pipe_spec(missing)

    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(PipeSpecError, match="not valid JSON"):
        load_pipe_spec(bad)

    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"steps": [{"box": "unknown"}]}), encoding="utf-8")
    with pytest.raises(PipeSpecError, match="not a valid pipe"):
        load_pipe_spec(unknown)


def test_load_pipe_spec_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "pipe.json"
    path.write_text(
        json.dumps({"name": "Test", "steps": [{"box": "limit", "count": 2}]}),
        encoding="utf-8",
    )

    spec = load_pipe_spec(path)

    assert spec.name == "Test"
    assert spec.steps[0].box == "limit"


def test_dedupe_uses_normalized_links() -> None:
    items = [
        make_item(1, "First", link="https://Example.com/post#comments"),
        make_item(2, "Second", link="https://example.com/post"),
        make_item(3, "Third", link="https://example.com/other"),
    ]

    result = DedupeBox("link").run(items, context=None)  # type: ignore[arg-type]

    assert [item.title for item in result] == ["First", "Third"]


def test_filter_checks_the_chosen_fields() -> None:
    items = [
        make_item(1, "Python release", content="FastAPI"),
        make_item(2, "Rust release", content="tokio"),
    ]

    by_title = FilterBox("python", ["title"]).run(items, context=None)  # type: ignore[arg-type]
    by_content = FilterBox("fastapi", ["content"]).run(items, context=None)  # type: ignore[arg-type]

    assert [item.title for item in by_title] == ["Python release"]
    assert [item.title for item in by_content] == ["Python release"]


def test_sort_puts_missing_dates_last() -> None:
    items = [
        make_item(1, "Old", published=datetime(2026, 10, 20, tzinfo=timezone.utc)),
        make_item(2, "No date"),
        make_item(3, "New", published=datetime(2026, 10, 27, tzinfo=timezone.utc)),
    ]

    result = SortBox("published", "desc").run(items, context=None)  # type: ignore[arg-type]

    assert [item.title for item in result] == ["New", "Old", "No date"]


def test_limit_keeps_the_front_of_the_stream() -> None:
    items = [make_item(1, "One"), make_item(2, "Two"), make_item(3, "Three")]

    assert [item.title for item in LimitBox(2).run(items, context=None)] == [  # type: ignore[arg-type]
        "One",
        "Two",
    ]


def test_merge_joins_fetch_branches() -> None:
    first = [make_item(1, "One")]
    second = [make_item(2, "Two")]
    context = RunContext(
        session=None,  # type: ignore[arg-type]
        settings=None,  # type: ignore[arg-type]
        client=None,  # type: ignore[arg-type]
        owner_id=1,
        sources=[first, second],
    )

    result = MergeBox().run(second, context)

    assert [item.title for item in result] == ["One", "Two"]
    assert context.sources == [result]


def test_fetch_box_stores_and_returns_items(
    settings: Settings,
    db_session: Session,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    context = RunContext(
        session=db_session,
        settings=settings,
        client=client,
        owner_id=ensure_local_user(db_session).id,
    )

    try:
        result = FetchBox(["https://example.com/feed.xml"]).run([], context)
        db_session.commit()
    finally:
        client.close()

    assert [item.title for item in result] == ["First post"]
    assert len(context.sources) == 1
    assert db_session.scalar(select(func.count()).select_from(Item)) == 1


def test_fulltext_box_stores_article_text(
    settings: Settings,
    db_session: Session,
) -> None:
    feed = Feed(
        owner_id=ensure_local_user(db_session).id,
        url="https://example.com/feed.xml",
        title="Example",
    )
    db_session.add(feed)
    db_session.flush()
    row = Item(
        feed_id=feed.id,
        guid="fulltext-1",
        title="Post",
        link="https://example.com/post",
        content="Short feed summary.",
    )
    db_session.add(row)
    db_session.commit()
    item = ItemOut.model_validate(row)

    paragraph = "A substantial sentence about the article topic. " * 12
    page = (
        "<html><body><article>"
        + "".join(f"<p>{paragraph}</p>" for _ in range(3))
        + "</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=page.encode(),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    context = RunContext(
        session=db_session,
        settings=settings.model_copy(update={"article_delay_seconds": 0}),
        client=client,
        owner_id=ensure_local_user(db_session).id,
    )

    try:
        result = FullTextBox().run([item], context)
        db_session.commit()
    finally:
        client.close()

    assert len(result) == 1
    assert result[0].fetch_status == "ok"
    assert "substantial sentence" in (result[0].content_full or "")
    assert row.fetch_status == "ok"


def test_run_pipe_applies_steps_in_order(
    settings: Settings,
    db_session: Session,
) -> None:
    client = httpx.Client()
    context = RunContext(
        session=db_session,
        settings=settings,
        client=client,
        owner_id=ensure_local_user(db_session).id,
    )
    items = [
        make_item(
            1,
            "Python one",
            link="https://example.com/one",
            published=datetime(2026, 10, 20, tzinfo=timezone.utc),
        ),
        make_item(
            2,
            "Python two",
            link="https://example.com/two",
            published=datetime(2026, 10, 27, tzinfo=timezone.utc),
        ),
        make_item(
            3,
            "Rust three",
            link="https://example.com/three",
            published=datetime(2026, 10, 26, tzinfo=timezone.utc),
        ),
    ]

    # Seed the current stream through the merge box's source list.
    context.sources = [items]
    spec = PipeSpec.model_validate(
        {
            "name": "Filtered",
            "steps": [
                {"box": "merge"},
                {"box": "filter", "keyword": "python"},
                {"box": "sort", "by": "published", "order": "desc"},
                {"box": "limit", "count": 1},
            ],
        }
    )

    try:
        result = run_pipe(spec, context)
    finally:
        client.close()

    assert result.name == "Filtered"
    assert [item.title for item in result.items] == ["Python two"]
    assert [step.box for step in result.steps] == ["merge", "filter", "sort", "limit"]
    assert result.steps[-1].items_in == 2
    assert result.steps[-1].items_out == 1
