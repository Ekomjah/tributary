from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Feed, Item, Share, User

__all__ = [
    "ClaimResult",
    "OwnShareLink",
    "SHARED_INBOX_TITLE",
    "SHARED_INBOX_URL",
    "SHARE_TTL",
    "ShareAlreadyClaimed",
    "ShareExpired",
    "ShareNotFound",
    "claim_share",
    "create_share",
    "find_share",
    "hash_token",
    "preview_excerpt",
    "preview_share",
    "sender_label",
    "shared_feed",
]

SHARED_INBOX_URL = "shared://inbox"
SHARED_INBOX_TITLE = "Shared with me"
SHARE_TTL = timedelta(days=30)

_SNAPSHOT_FIELDS = (
    "title",
    "link",
    "published",
    "content",
    "content_html",
    "author",
    "cover_image",
    "cover_image_alt",
    "cover_caption",
    "content_full",
    "content_fetched_at",
    "fetch_status",
    "discussion_url",
    "points",
    "comment_count",
    "source",
    "summary",
    "why_care",
)
_DATETIME_FIELDS = ("published", "content_fetched_at")


class ShareError(RuntimeError):
    """Base class for share-link failures that map to user-facing responses."""


class ShareNotFound(ShareError):
    pass


class ShareExpired(ShareError):
    pass


class ShareAlreadyClaimed(ShareError):
    pass


class OwnShareLink(ShareError):
    pass


@dataclass(slots=True)
class ClaimResult:
    item: Item
    feed: Feed
    already_claimed: bool = False


def hash_token(token: str) -> str:
    """Hash a link token for storage; the raw token is never persisted."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sender_label(user: User) -> str:
    """Return the name a recipient sees for the sender."""

    for value in (user.name, user.email):
        label = (value or "").strip()
        if label:
            return label[:200]
    return "A Tributary reader"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def snapshot_item(item: Item, sender: User) -> dict[str, Any]:
    """Copy the article exactly as the sender's reader shows it."""

    snapshot: dict[str, Any] = {
        field: getattr(item, field, None) for field in _SNAPSHOT_FIELDS
    }
    for field in _DATETIME_FIELDS:
        snapshot[field] = _iso(snapshot[field])

    feed_title = (item.origin_feed_title or item.feed.title or "").strip()
    snapshot["origin_feed_title"] = feed_title[:500] or None
    snapshot["shared_by"] = sender_label(sender)
    return snapshot


def create_share(db: Session, item: Item, sender: User) -> tuple[Share, str]:
    """Create a single-use link and return the raw token exactly once."""

    token = secrets.token_urlsafe(32)
    now = utcnow()
    share = Share(
        token_hash=hash_token(token),
        sender_id=sender.id,
        source_item_id=item.id,
        snapshot_json=snapshot_item(item, sender),
        created_at=now,
        expires_at=now + SHARE_TTL,
    )
    db.add(share)
    db.flush()
    return share, token


def find_share(db: Session, token: str) -> Share:
    share = db.scalar(select(Share).where(Share.token_hash == hash_token(token)))
    if share is None:
        raise ShareNotFound
    return share


def _unexpired(share: Share, now: datetime | None = None) -> None:
    if share.expires_at <= (now or utcnow()):
        raise ShareExpired


def preview_excerpt(snapshot: dict[str, Any], limit: int = 280) -> str:
    """Return a short plain-text preview for the claim page."""

    raw = str(snapshot.get("summary") or snapshot.get("content") or "").strip()
    if not raw:
        return ""
    text = " ".join(raw.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def preview_share(share: Share, viewer: User) -> dict[str, Any]:
    """Describe a shared article without revealing another claimer's copy id."""

    now = utcnow()
    _unexpired(share, now)
    snapshot = share.snapshot_json or {}
    claimed_by_me = (
        share.claimed_by_id is not None and share.claimed_by_id == viewer.id
    )
    return {
        "title": str(snapshot.get("title") or "Untitled"),
        "excerpt": preview_excerpt(snapshot),
        "author": snapshot.get("author"),
        "source": snapshot.get("source"),
        "origin_feed_title": snapshot.get("origin_feed_title"),
        "shared_by": snapshot.get("shared_by"),
        "shared_at": share.created_at,
        "expires_at": share.expires_at,
        "claimed": share.claimed_at is not None,
        "claimed_by_me": claimed_by_me,
        "shared_by_me": share.sender_id == viewer.id,
        "claimed_item_id": share.claimed_item_id if claimed_by_me else None,
    }


def shared_feed(db: Session, owner_id: int) -> Feed:
    """Return the recipient's single shared inbox, creating it on first use."""

    query = select(Feed).where(
        Feed.owner_id == owner_id,
        Feed.kind == "shared",
        Feed.url == SHARED_INBOX_URL,
    )
    feed = db.scalar(query)
    if feed is not None:
        return feed

    try:
        # A second request can create the same inbox concurrently. Keep the
        # duplicate insert inside a savepoint so the claim around it survives.
        with db.begin_nested():
            feed = Feed(
                owner_id=owner_id,
                url=SHARED_INBOX_URL,
                title=SHARED_INBOX_TITLE,
                kind="shared",
            )
            db.add(feed)
            db.flush()
    except IntegrityError:
        feed = db.scalar(query)
        if feed is None:  # pragma: no cover - defensive
            raise
    return feed


def _claimed_copy(db: Session, share: Share, recipient: User) -> ClaimResult | None:
    if share.claimed_by_id != recipient.id or share.claimed_item_id is None:
        return None
    item = db.get(Item, share.claimed_item_id)
    if item is None:
        return None
    feed = db.get(Feed, item.feed_id)
    if feed is None:
        return None
    return ClaimResult(item=item, feed=feed, already_claimed=True)


def claim_share(db: Session, share: Share, recipient: User) -> ClaimResult:
    """Copy the snapshot into the recipient's shared inbox.

    The claim row is updated conditionally so two recipients holding the same
    link cannot both receive a copy.
    """

    now = utcnow()
    _unexpired(share, now)

    if share.sender_id == recipient.id:
        raise OwnShareLink

    existing = _claimed_copy(db, share, recipient)
    if existing is not None:
        return existing
    if share.claimed_at is not None:
        raise ShareAlreadyClaimed

    claim_update = (
        update(Share)
        .where(Share.id == share.id, Share.claimed_at.is_(None))
        .values(claimed_at=now, claimed_by_id=recipient.id)
        .execution_options(synchronize_session=False)
    )
    claimed = db.execute(claim_update)
    if claimed.rowcount != 1:
        db.expire(share)
        db.refresh(share)
        existing = _claimed_copy(db, share, recipient)
        if existing is not None:
            return existing
        raise ShareAlreadyClaimed

    db.refresh(share)
    snapshot = share.snapshot_json or {}
    feed = shared_feed(db, recipient.id)

    item = Item(
        feed_id=feed.id,
        guid=f"urn:tributary:share:{share.id}",
        title=str(snapshot.get("title") or "")[:1000],
        link=snapshot.get("link"),
        published=_datetime(snapshot.get("published")),
        content=str(snapshot.get("content") or ""),
        content_html=snapshot.get("content_html"),
        author=snapshot.get("author"),
        cover_image=snapshot.get("cover_image"),
        cover_image_alt=snapshot.get("cover_image_alt"),
        cover_caption=snapshot.get("cover_caption"),
        content_full=snapshot.get("content_full"),
        content_fetched_at=_datetime(snapshot.get("content_fetched_at")),
        fetch_status=snapshot.get("fetch_status"),
        discussion_url=snapshot.get("discussion_url"),
        points=snapshot.get("points"),
        comment_count=snapshot.get("comment_count"),
        shared_by=snapshot.get("shared_by"),
        shared_at=share.created_at,
        origin_feed_title=snapshot.get("origin_feed_title"),
        source=snapshot.get("source"),
        summary=snapshot.get("summary"),
        why_care=snapshot.get("why_care"),
        is_read=False,
        starred=False,
        decision=None,
        fetched_at=now,
    )
    db.add(item)
    db.flush()

    share.claimed_item_id = item.id
    db.flush()
    return ClaimResult(item=item, feed=feed, already_claimed=False)
