from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tributary.api.security import get_current_user
from tributary.db import utcnow
from tributary.models import Feed, Item, Share, User


def seed_user(db: Session, sub: str, name: str) -> User:
    user = User(auth0_sub=sub, name=name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_feed(db: Session, owner: User, *, title: str = "Sender feed") -> Feed:
    feed = Feed(
        owner_id=owner.id,
        url="https://example.com/feed.xml",
        title=title,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def seed_item(db: Session, feed: Feed, *, title: str = "A shared article") -> Item:
    item = Item(
        feed_id=feed.id,
        guid="shared-article",
        title=title,
        link="https://example.com/posts/shared",
        content="Snapshot body.",
        content_html="<p>Snapshot body.</p>",
        content_full="The full article the sender read.",
        fetch_status="ok",
        discussion_url="https://example.com/discussion",
        points=42,
        comment_count=7,
        source="Example",
        summary="A short summary.",
        is_read=True,
        starred=True,
        decision="keep",
        fetched_at=utcnow(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture
def act_as(client: TestClient):
    original = dict(client.app.dependency_overrides)

    def _act_as(user: User) -> None:
        client.app.dependency_overrides[get_current_user] = lambda: user

    yield _act_as

    client.app.dependency_overrides.clear()
    client.app.dependency_overrides.update(original)


def share_link(client: TestClient, item: Item) -> dict:
    response = client.post(f"/api/items/{item.id}/share-link")
    assert response.status_code == 201
    return response.json()


def test_share_link_creates_an_independent_recipient_copy(
    client: TestClient,
    db_session: Session,
    act_as,
) -> None:
    sender = seed_user(db_session, "auth0|sender", "Sender")
    recipient = seed_user(db_session, "auth0|recipient", "Recipient")
    sender_feed = seed_feed(db_session, sender)
    source = seed_item(db_session, sender_feed)
    source_id = source.id

    act_as(sender)
    link = share_link(client, source)
    assert link["token"]
    assert link["expires_at"]

    stored = db_session.scalar(select(Share))
    assert stored is not None
    assert stored.token_hash != link["token"]

    act_as(recipient)
    preview = client.get(f"/api/shares/{link['token']}")
    assert preview.status_code == 200
    body = preview.json()
    assert body["title"] == "A shared article"
    assert body["shared_by"] == "Sender"
    assert body["origin_feed_title"] == "Sender feed"
    assert body["claimed"] is False
    assert body["shared_by_me"] is False
    assert body["claimed_item_id"] is None

    claimed = client.post(f"/api/shares/{link['token']}/claim")
    assert claimed.status_code == 200
    payload = claimed.json()
    copy = payload["item"]
    inbox = payload["feed"]
    assert payload["already_claimed"] is False
    assert inbox["kind"] == "shared"
    assert inbox["url"] == "shared://inbox"
    assert inbox["title"] == "Shared with me"
    assert copy["feed_id"] == inbox["id"]
    assert copy["id"] != source_id
    assert copy["title"] == "A shared article"
    assert copy["content_full"] == "The full article the sender read."
    assert copy["link"] == "https://example.com/posts/shared"
    assert copy["shared_by"] == "Sender"
    assert copy["origin_feed_title"] == "Sender feed"
    assert copy["is_read"] is False
    assert copy["starred"] is False
    assert copy["decision"] is None
    assert copy["labels"] == []

    feeds = client.get("/api/feeds").json()
    assert [feed["id"] for feed in feeds] == [inbox["id"]]
    all_items = client.get("/api/items").json()
    assert [item["id"] for item in all_items["items"]] == [copy["id"]]
    inbox_items = client.get(f"/api/items?feed_id={inbox['id']}").json()
    assert [item["id"] for item in inbox_items["items"]] == [copy["id"]]

    # Recipient actions stay on the copy.
    updated = client.patch(
        f"/api/items/{copy['id']}",
        json={"is_read": True, "starred": True, "decision": "drop"},
    )
    assert updated.status_code == 200
    db_session.expire_all()
    original = db_session.get(Item, source_id)
    assert original is not None
    assert original.is_read is True
    assert original.starred is True
    assert original.decision == "keep"

    # Repeated claim by the same recipient is idempotent.
    again = client.post(f"/api/shares/{link['token']}/claim")
    assert again.status_code == 200
    assert again.json()["already_claimed"] is True
    assert again.json()["item"]["id"] == copy["id"]
    guid = f"urn:tributary:share:{stored.id}"
    copies = db_session.scalars(
        select(Item).where(Item.feed_id == inbox["id"], Item.guid == guid)
    ).all()
    assert [item.id for item in copies] == [copy["id"]]


def test_share_link_is_single_use_and_rejects_the_sender(
    client: TestClient,
    db_session: Session,
    act_as,
) -> None:
    sender = seed_user(db_session, "auth0|sender", "Sender")
    first = seed_user(db_session, "auth0|first", "First")
    second = seed_user(db_session, "auth0|second", "Second")
    source = seed_item(db_session, seed_feed(db_session, sender))

    act_as(sender)
    link = share_link(client, source)
    own_preview = client.get(f"/api/shares/{link['token']}")
    assert own_preview.status_code == 200
    assert own_preview.json()["shared_by_me"] is True
    own = client.post(f"/api/shares/{link['token']}/claim")
    assert own.status_code == 400
    assert "own share link" in own.json()["detail"]

    act_as(first)
    assert client.post(f"/api/shares/{link['token']}/claim").status_code == 200
    act_as(second)
    conflict = client.post(f"/api/shares/{link['token']}/claim")
    assert conflict.status_code == 409
    preview = client.get(f"/api/shares/{link['token']}")
    assert preview.status_code == 200
    assert preview.json()["claimed"] is True
    assert preview.json()["claimed_by_me"] is False
    assert preview.json()["claimed_item_id"] is None


def test_claim_survives_deleting_the_source_feed(
    client: TestClient,
    db_session: Session,
    act_as,
) -> None:
    sender = seed_user(db_session, "auth0|sender", "Sender")
    recipient = seed_user(db_session, "auth0|recipient", "Recipient")
    sender_feed = seed_feed(db_session, sender)
    source = seed_item(db_session, sender_feed)

    act_as(sender)
    link = share_link(client, source)
    db_session.delete(sender_feed)
    db_session.commit()

    act_as(recipient)
    claimed = client.post(f"/api/shares/{link['token']}/claim")
    assert claimed.status_code == 200
    copy = claimed.json()["item"]
    assert copy["title"] == "A shared article"
    assert copy["content_full"] == "The full article the sender read."


def test_expired_and_unknown_links_are_rejected(
    client: TestClient,
    db_session: Session,
    act_as,
) -> None:
    sender = seed_user(db_session, "auth0|sender", "Sender")
    recipient = seed_user(db_session, "auth0|recipient", "Recipient")
    source = seed_item(db_session, seed_feed(db_session, sender))

    act_as(sender)
    link = share_link(client, source)
    stored = db_session.scalar(select(Share))
    assert stored is not None
    stored.expires_at = utcnow() - timedelta(minutes=1)
    db_session.commit()

    act_as(recipient)
    assert client.get(f"/api/shares/{link['token']}").status_code == 410
    assert client.post(f"/api/shares/{link['token']}/claim").status_code == 410
    assert client.get("/api/shares/not-a-real-token").status_code == 404
    assert client.post("/api/shares/not-a-real-token/claim").status_code == 404


def test_shared_inbox_refresh_has_a_friendly_message(
    client: TestClient,
    db_session: Session,
    act_as,
) -> None:
    sender = seed_user(db_session, "auth0|sender", "Sender")
    recipient = seed_user(db_session, "auth0|recipient", "Recipient")
    source = seed_item(db_session, seed_feed(db_session, sender))

    act_as(sender)
    link = share_link(client, source)
    act_as(recipient)
    inbox = client.post(f"/api/shares/{link['token']}/claim").json()["feed"]

    response = client.post(f"/api/feeds/{inbox['id']}/refresh")
    assert response.status_code == 400
    assert "someone shares" in response.json()["detail"]


def test_only_the_source_owner_can_create_a_share_link(
    client: TestClient,
    db_session: Session,
    act_as,
) -> None:
    owner = seed_user(db_session, "auth0|owner", "Owner")
    stranger = seed_user(db_session, "auth0|stranger", "Stranger")
    source = seed_item(db_session, seed_feed(db_session, owner))

    act_as(stranger)
    assert client.post(f"/api/items/{source.id}/share-link").status_code == 404
