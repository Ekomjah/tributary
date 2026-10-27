from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tributary.models import BoxCache, Feed, Item, Label, Pipe, Run, item_labels

EXPECTED_TABLES = {
    "box_cache",
    "feeds",
    "item_labels",
    "items",
    "labels",
    "pipes",
    "runs",
}


def test_all_mvp_tables_are_created(engine) -> None:
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES


def test_models_round_trip(db_session: Session) -> None:
    published = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

    feed = Feed(url="https://example.com/feed.xml", title="Example feed")
    item = Item(
        feed=feed,
        guid="item-1",
        title="A post",
        link="https://example.com/posts/1",
        published=published,
        content="The post body.",
    )
    label = Label(name="python")
    item.labels.append(label)

    pipe = Pipe(name="Test pipe", spec_json={"name": "Test pipe", "steps": []})
    run = Run(pipe=pipe, status="success", seconds=1.25, result_count=1)
    cache = BoxCache(
        item=item,
        box="summarize",
        params_hash="a" * 64,
        model="gemma3:1b",
        output="One line about the post.",
    )

    db_session.add_all([feed, item, label, pipe, run, cache])
    db_session.commit()

    assert feed.id is not None
    assert item.id is not None
    assert item.feed is feed
    assert feed.items == [item]
    assert item.labels == [label]
    assert label.items == [item]
    assert item.box_cache == [cache]
    assert cache.item is item
    assert run.pipe is pipe
    assert pipe.runs == [run]

    assert item.published == published
    assert item.published.tzinfo is timezone.utc
    assert item.fetched_at.tzinfo is timezone.utc
    assert run.started.tzinfo is timezone.utc


def test_item_guid_is_unique_per_feed(db_session: Session) -> None:
    feed = Feed(url="https://example.com/feed.xml", title="Example feed")
    db_session.add(feed)
    db_session.commit()

    db_session.add_all(
        [
            Item(feed_id=feed.id, guid="same-guid"),
            Item(feed_id=feed.id, guid="same-guid"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_decision_only_accepts_keep_drop_or_null(db_session: Session) -> None:
    feed = Feed(url="https://example.com/feed.xml", title="Example feed")
    item = Item(feed=feed, guid="item-1")
    db_session.add_all([feed, item])
    db_session.commit()

    item.decision = "maybe"
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_label_names_are_case_insensitive(db_session: Session) -> None:
    db_session.add(Label(name="Python"))
    db_session.commit()

    db_session.add(Label(name="python"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_feed_delete_cascades_items_cache_and_item_labels(db_session: Session) -> None:
    feed = Feed(url="https://example.com/feed.xml", title="Example feed")
    item = Item(feed=feed, guid="item-1", title="A post")
    label = Label(name="python")
    item.labels.append(label)
    cache = BoxCache(
        item=item,
        box="summarize",
        params_hash="a" * 64,
        model="gemma3:1b",
        output="One line.",
    )
    db_session.add_all([feed, item, label, cache])
    db_session.commit()

    item_id = item.id
    label_id = label.id

    db_session.delete(feed)
    db_session.commit()

    assert db_session.get(Item, item_id) is None
    assert db_session.get(BoxCache, (item_id, "summarize", "a" * 64, "gemma3:1b")) is None
    assert db_session.get(Label, label_id) is not None
    assert db_session.scalar(select(func.count()).select_from(item_labels)) == 0


def test_pipe_delete_cascades_runs(db_session: Session) -> None:
    pipe = Pipe(name="Test pipe", spec_json={"name": "Test pipe", "steps": []})
    run = Run(pipe=pipe, status="running")
    db_session.add_all([pipe, run])
    db_session.commit()

    run_id = run.id
    db_session.delete(pipe)
    db_session.commit()

    assert db_session.get(Run, run_id) is None
