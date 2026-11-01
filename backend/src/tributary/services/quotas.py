from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..db import utcnow
from ..models import Pipe, UsageEvent, User

UsageKind = Literal["feed_refresh", "pipe_run", "search"]

WINDOW = timedelta(hours=1)
_RETENTION = timedelta(days=1)

_DESCRIPTIONS: dict[UsageKind, str] = {
    "feed_refresh": "refresh feeds",
    "pipe_run": "run pipes",
    "search": "make searches",
}


class LimitExceeded(RuntimeError):
    """A hosted account reached a quota or a fixed resource limit."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 429,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def _independent_session(session: Session) -> Session:
    """Open a short session so quota writes survive a later rollback."""

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    return factory()


def _window_start(now: datetime) -> datetime:
    return now - WINDOW


def _retry_after(oldest: datetime, now: datetime) -> int:
    remaining = (oldest + WINDOW - now).total_seconds()
    return max(1, ceil(remaining))


def _limit_message(kind: UsageKind, limit: int, retry_after: int | None) -> str:
    if kind == "search":
        phrase = f"make {limit} search{'es' if limit != 1 else ''} per hour"
    else:
        phrase = (
            f"{_DESCRIPTIONS[kind]} {limit} "
            f"time{'' if limit == 1 else 's'} per hour"
        )
    message = f"You can {phrase}."
    if retry_after is not None:
        minutes = max(1, ceil(retry_after / 60))
        message = (
            f"You can {phrase}. "
            f"Try again in {minutes} minute{'' if minutes == 1 else 's'}."
        )
    return message


def consume(
    session: Session,
    *,
    user_id: int,
    kind: UsageKind,
    limit: int,
    settings: Settings,
    now: datetime | None = None,
) -> None:
    """Record one unit of usage, or raise ``LimitExceeded`` when full.

    Local installations return immediately: configured quotas only protect the
    hosted profile. A separate transaction commits the event before the caller
    performs the external work, so a later pipe failure cannot refund it.
    """

    if not settings.is_cloud:
        return

    current = now or utcnow()
    quota_session = _independent_session(session)
    try:
        # Serialize checks for one user across workers. PostgreSQL honors the
        # row lock; SQLite only runs the local profile, which never gets here.
        quota_session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )
        used = int(
            quota_session.scalar(
                select(func.count())
                .select_from(UsageEvent)
                .where(
                    UsageEvent.user_id == user_id,
                    UsageEvent.kind == kind,
                    UsageEvent.created_at > _window_start(current),
                )
            )
            or 0
        )
        if used >= limit:
            oldest = quota_session.scalar(
                select(func.min(UsageEvent.created_at)).where(
                    UsageEvent.user_id == user_id,
                    UsageEvent.kind == kind,
                    UsageEvent.created_at > _window_start(current),
                )
            )
            retry_after = _retry_after(oldest, current) if oldest is not None else 3600
            quota_session.rollback()
            raise LimitExceeded(
                _limit_message(kind, limit, retry_after),
                retry_after=retry_after,
            )

        quota_session.execute(
            delete(UsageEvent).where(
                UsageEvent.created_at < current - _RETENTION,
            )
        )
        quota_session.add(UsageEvent(user_id=user_id, kind=kind, created_at=current))
        quota_session.commit()
    finally:
        quota_session.close()


def ensure_pipe_slot(
    session: Session,
    *,
    user_id: int,
    limit: int,
    settings: Settings,
) -> None:
    """Lock the user row and reject a new pipe when the saved-pipe cap is full.

    The caller must insert the pipe and commit while the lock is still held, so
    two concurrent creates cannot both pass the count.
    """

    if not settings.is_cloud:
        return

    session.execute(select(User.id).where(User.id == user_id).with_for_update())
    used = int(
        session.scalar(
            select(func.count())
            .select_from(Pipe)
            .where(Pipe.owner_id == user_id)
        )
        or 0
    )
    if used >= limit:
        singular = "pipe" if limit == 1 else "pipes"
        raise LimitExceeded(
            f"You can save up to {limit} {singular}. Delete one to create another.",
            status_code=409,
        )
