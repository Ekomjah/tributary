from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tributary.api.security import get_current_user
from tributary.config import Settings
from tributary.models import (
    Feed,
    Item,
    Label,
    Pipe,
    Run,
    SearchCache,
    User,
    pipe_feed_items,
)
from tributary.services import feeds as feed_service
from tributary.services import pipe_feeds, search

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Owned feed</title>
    <link>https://example.com/</link>
    <description>An owned feed</description>
    <item>
      <title>Owned post</title>
      <link>https://example.com/posts/owned</link>
      <guid>owned-1</guid>
      <description>Owned body.</description>
    </item>
  </channel>
</rss>
"""


class StubBackend:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


def other_user(db: Session, sub: str = "auth0|other") -> User:
    user = User(auth0_sub=sub, name="Other")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_feed(
    db: Session,
    owner: User,
    *,
    url: str = "https://example.com/feed.xml",
    title: str = "Example",
    kind: str = "feed",
    pipe_id: int | None = None,
) -> Feed:
    feed = Feed(
        owner_id=owner.id,
        url=url,
        title=title,
        kind=kind,
        pipe_id=pipe_id,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def seed_item(
    db: Session,
    feed: Feed,
    *,
    guid: str,
    title: str = "Item",
    link: str | None = None,
) -> Item:
    item = Item(
        feed_id=feed.id,
        guid=guid,
        title=title,
        link=link or f"https://example.com/posts/{guid}",
        content="Body.",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def seed_label(db: Session, owner: User, name: str) -> Label:
    label = Label(owner_id=owner.id, name=name)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


def seed_pipe(db: Session, owner: User, name: str = "Pipe") -> Pipe:
    pipe = Pipe(
        owner_id=owner.id,
        name=name,
        spec_json={"name": name, "steps": []},
    )
    db.add(pipe)
    db.commit()
    db.refresh(pipe)
    return pipe


@pytest.fixture
def act_as(client: TestClient):
    """Override the current user so local-mode tests can simulate tenants."""

    original = dict(client.app.dependency_overrides)

    def _act_as(user: User) -> None:
        client.app.dependency_overrides[get_current_user] = lambda: user

    yield _act_as

    client.app.dependency_overrides.clear()
    client.app.dependency_overrides.update(original)


def test_duplicate_urls_and_label_names_are_per_owner(
    db_session: Session,
    local_user: User,
) -> None:
    other = other_user(db_session)

    db_session.add_all(
        [
            Feed(owner_id=local_user.id, url="https://example.com/feed.xml", title="A"),
            Feed(owner_id=other.id, url="https://example.com/feed.xml", title="B"),
            Label(owner_id=local_user.id, name="Python"),
            Label(owner_id=other.id, name="python"),
        ]
    )
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Feed)) == 2
    assert db_session.scalar(select(func.count()).select_from(Label)) == 2

    db_session.add(Feed(owner_id=local_user.id, url="https://example.com/feed.xml"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    db_session.add(Label(owner_id=local_user.id, name="PYTHON"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_feed_endpoints_are_owner_scoped(
    client: TestClient,
    db_session: Session,
    local_user: User,
    act_as,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = other_user(db_session)
    mine = seed_feed(db_session, local_user, title="Mine")
    theirs = seed_feed(db_session, other, title="Theirs")
    other_pipe = seed_pipe(db_session, other, name="Their pipe")

    act_as(local_user)

    body = client.get("/api/feeds").json()
    assert [feed["id"] for feed in body] == [mine.id]

    assert client.get(f"/api/feeds/{theirs.id}").status_code == 404
    assert client.delete(f"/api/feeds/{theirs.id}").status_code == 404
    assert client.post(f"/api/feeds/{theirs.id}/refresh").status_code == 404
    assert (
        client.post("/api/feeds/pipe", json={"pipe_id": other_pipe.id}).status_code
        == 404
    )

    seen: dict[str, int] = {}

    def fake_refresh(factory, settings, *, owner_id):
        seen["owner_id"] = owner_id
        return []

    monkeypatch.setattr(feed_service, "refresh_feeds", fake_refresh)
    assert client.post("/api/feeds/refresh").status_code == 200
    assert seen["owner_id"] == local_user.id


def test_item_and_label_endpoints_are_owner_scoped(
    client: TestClient,
    db_session: Session,
    local_user: User,
    act_as,
) -> None:
    other = other_user(db_session)
    mine = seed_feed(db_session, local_user, title="Mine")
    theirs = seed_feed(db_session, other, title="Theirs")
    my_item = seed_item(db_session, mine, guid="mine")
    their_item = seed_item(db_session, theirs, guid="theirs")
    my_label = seed_label(db_session, local_user, "Mine")
    their_label = seed_label(db_session, other, "Theirs")

    act_as(local_user)

    page = client.get("/api/items").json()
    assert [item["id"] for item in page["items"]] == [my_item.id]

    assert client.get(f"/api/items/{their_item.id}").status_code == 404
    assert client.patch(f"/api/items/{their_item.id}", json={"is_read": True}).status_code == 404
    assert client.post(f"/api/items/{their_item.id}/fetch").status_code == 404
    assert (
        client.post(f"/api/items/{their_item.id}/labels/{their_label.id}").status_code
        == 404
    )

    response = client.patch(
        f"/api/items/{my_item.id}",
        json={"label_ids": [their_label.id]},
    )
    assert response.status_code == 422

    labels = client.get("/api/labels").json()
    assert [label["id"] for label in labels] == [my_label.id]
    assert client.delete(f"/api/labels/{their_label.id}").status_code == 404


def test_pipe_and_run_endpoints_are_owner_scoped(
    client: TestClient,
    db_session: Session,
    local_user: User,
    act_as,
) -> None:
    other = other_user(db_session)
    my_pipe = seed_pipe(db_session, local_user, name="Mine")
    their_pipe = seed_pipe(db_session, other, name="Theirs")
    my_feed = seed_feed(db_session, local_user, title="Mine")
    their_feed = seed_feed(db_session, other, title="Theirs")
    my_item = seed_item(db_session, my_feed, guid="mine")
    their_item = seed_item(db_session, their_feed, guid="theirs")

    my_run = Run(pipe_id=my_pipe.id, status="success", item_ids_json=[my_item.id, their_item.id])
    their_run = Run(pipe_id=their_pipe.id, status="success", item_ids_json=[their_item.id])
    db_session.add_all([my_run, their_run])
    db_session.commit()
    db_session.refresh(my_run)
    db_session.refresh(their_run)

    act_as(local_user)

    pipes = client.get("/api/pipes").json()
    assert [pipe["id"] for pipe in pipes] == [my_pipe.id]

    assert client.get(f"/api/pipes/{their_pipe.id}").status_code == 404
    assert (
        client.patch(
            f"/api/pipes/{their_pipe.id}",
            json={"name": "Renamed"},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/pipes/{their_pipe.id}").status_code == 404
    assert client.post(f"/api/pipes/{their_pipe.id}/run").status_code == 404
    assert client.post(f"/api/pipes/{their_pipe.id}/runs").status_code == 404

    runs = client.get("/api/runs").json()
    assert [run["id"] for run in runs] == [my_run.id]
    assert client.get(f"/api/runs/{their_run.id}").status_code == 404
    assert client.get(f"/api/runs/{their_run.id}/results").status_code == 404
    assert client.get(f"/api/runs?pipe_id={their_pipe.id}").status_code == 404

    results = client.get(f"/api/runs/{my_run.id}/results").json()
    assert [item["id"] for item in results["items"]] == [my_item.id]


def test_search_feeds_are_owner_scoped(
    client: TestClient,
    db_session: Session,
    settings: Settings,
    local_user: User,
    act_as,
) -> None:
    other = other_user(db_session)
    backend = StubBackend(
        {
            "news_results": [
                {
                    "title": "A shared story",
                    "link": "https://example.com/story",
                    "source": {"name": "Example News"},
                    "snippet": "A story.",
                }
            ]
        }
    )
    params = search.make_params(settings, "AI regulation")

    first = search.run_search(
        db_session,
        settings,
        params,
        owner_id=local_user.id,
        backend=backend,
    )
    db_session.commit()
    second = search.run_search(
        db_session,
        settings,
        params,
        owner_id=other.id,
        backend=backend,
    )
    db_session.commit()

    assert first.cached is False
    assert second.cached is True
    assert len(backend.calls) == 1
    assert db_session.scalar(select(func.count()).select_from(SearchCache)) == 1

    search_feeds = db_session.scalars(
        select(Feed).where(Feed.kind == "search").order_by(Feed.owner_id)
    ).all()
    assert {feed.owner_id for feed in search_feeds} == {local_user.id, other.id}
    assert len({feed.url for feed in search_feeds}) == 1

    their_feed = next(feed for feed in search_feeds if feed.owner_id == other.id)

    act_as(local_user)

    body = client.get("/api/feeds").json()
    assert [feed["id"] for feed in body] == [
        feed.id for feed in search_feeds if feed.owner_id == local_user.id
    ]
    assert client.get(f"/api/items?feed_id={their_feed.id}").status_code == 404

    # Search results stay out of the default reader views.
    assert client.get("/api/items").json()["items"] == []


def test_refresh_is_owner_scoped(
    session_factory: sessionmaker[Session],
    settings: Settings,
    local_user: User,
) -> None:
    other = other_user_from_factory(session_factory)
    with session_factory() as session:
        mine = Feed(
            owner_id=local_user.id,
            url="https://example.com/mine.xml",
            title="Mine",
        )
        theirs = Feed(
            owner_id=other.id,
            url="https://example.com/theirs.xml",
            title="Theirs",
        )
        session.add_all([mine, theirs])
        session.commit()
        mine_id = mine.id
        theirs_id = theirs.id

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("mine.xml"):
            return httpx.Response(200, content=RSS.encode())
        return httpx.Response(500, text="boom")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = feed_service.refresh_feeds(
            session_factory,
            settings,
            owner_id=local_user.id,
            client=client,
        )

    assert [result.url for result in results] == ["https://example.com/mine.xml"]
    with session_factory() as session:
        stored_mine = session.get(Feed, mine_id)
        stored_theirs = session.get(Feed, theirs_id)
        assert stored_mine is not None
        assert stored_theirs is not None
        assert stored_mine.last_fetched is not None
        assert stored_mine.last_error is None
        assert stored_theirs.last_fetched is None
        assert stored_theirs.last_error is None
        assert session.scalar(select(func.count()).select_from(Item)) == 1

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = feed_service.refresh_feeds(
            session_factory,
            settings,
            owner_id=other.id,
            client=client,
        )

    assert [result.url for result in results] == ["https://example.com/theirs.xml"]
    with session_factory() as session:
        stored_theirs = session.get(Feed, theirs_id)
        assert stored_theirs is not None
        assert stored_theirs.last_error is not None


def other_user_from_factory(session_factory: sessionmaker[Session]) -> User:
    with session_factory() as session:
        user = other_user(session)
        session.expunge(user)
    return user


def test_pipe_feed_membership_excludes_other_owners_items(
    db_session: Session,
    local_user: User,
) -> None:
    other = other_user(db_session)
    my_pipe = seed_pipe(db_session, local_user)
    my_feed = seed_feed(
        db_session,
        local_user,
        url=f"pipe://{my_pipe.id}",
        kind="pipe",
        pipe_id=my_pipe.id,
    )
    my_item = seed_item(db_session, my_feed, guid="mine")
    their_feed = seed_feed(db_session, other, title="Theirs")
    their_item = seed_item(db_session, their_feed, guid="theirs")

    pipe_feeds._replace_membership(
        db_session,
        my_feed,
        [my_item.id, their_item.id],
    )
    db_session.commit()

    member_ids = set(
        db_session.scalars(
            select(pipe_feed_items.c.item_id).where(
                pipe_feed_items.c.feed_id == my_feed.id
            )
        ).all()
    )
    assert member_ids == {my_item.id}


def test_refresh_pipe_feed_rejects_a_cross_owner_pipe(
    db_session: Session,
    settings: Settings,
    local_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = other_user(db_session)
    their_pipe = seed_pipe(db_session, other)
    my_feed = seed_feed(
        db_session,
        local_user,
        url=f"pipe://{their_pipe.id}",
        kind="pipe",
        pipe_id=their_pipe.id,
    )

    def unexpected_execution(*args, **kwargs):
        raise AssertionError("a cross-owner pipe must not run")

    monkeypatch.setattr(pipe_feeds, "execute_pipe", unexpected_execution)

    result = pipe_feeds.refresh_pipe_feed(db_session, my_feed, settings=settings)

    assert result.feed is my_feed
    assert result.error is not None
    assert "another reader" in result.error
    assert db_session.scalar(select(func.count()).select_from(Run)) == 0
