from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tributary.api.security import get_current_user
from tributary.config import Settings
from tributary.db import utcnow
from tributary.models import Pipe, UsageEvent, User
from tributary.services import quotas

EMPTY_PIPE = {"name": "Quota pipe", "steps": [{"box": "limit", "count": 1}]}


class FakeBackend:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {"news_results": []}
        self.calls: list[dict] = []

    def search(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return self.payload


@pytest.fixture
def hosted_settings(settings: Settings) -> Settings:
    """Cloud quota behavior without requiring a PostgreSQL test server."""

    return settings.model_copy(update={"dev_env": "test"})


def _count(db: Session, kind: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.kind == kind)
        )
        or 0
    )


def test_local_mode_never_records_usage(
    settings: Settings,
    db_session: Session,
    local_user: User,
) -> None:
    for _ in range(20):
        quotas.consume(
            db_session,
            user_id=local_user.id,
            kind="pipe_run",
            limit=3,
            settings=settings,
        )
        quotas.consume(
            db_session,
            user_id=local_user.id,
            kind="search",
            limit=3,
            settings=settings,
        )
        quotas.consume(
            db_session,
            user_id=local_user.id,
            kind="feed_refresh",
            limit=10,
            settings=settings,
        )

    assert _count(db_session, "pipe_run") == 0
    assert _count(db_session, "search") == 0
    assert _count(db_session, "feed_refresh") == 0


def test_local_mode_ignores_the_pipe_cap(
    settings: Settings,
    db_session: Session,
    local_user: User,
) -> None:
    for index in range(20):
        db_session.add(Pipe(owner_id=local_user.id, name=f"Pipe {index}"))
    db_session.commit()

    quotas.ensure_pipe_slot(
        db_session,
        user_id=local_user.id,
        limit=1,
        settings=settings,
    )


def test_consume_enforces_the_rolling_limit(
    hosted_settings: Settings,
    db_session: Session,
    local_user: User,
) -> None:
    for _ in range(3):
        quotas.consume(
            db_session,
            user_id=local_user.id,
            kind="pipe_run",
            limit=3,
            settings=hosted_settings,
        )

    with pytest.raises(quotas.LimitExceeded) as info:
        quotas.consume(
            db_session,
            user_id=local_user.id,
            kind="pipe_run",
            limit=3,
            settings=hosted_settings,
        )

    assert info.value.status_code == 429
    assert info.value.retry_after is not None
    assert 1 <= info.value.retry_after <= 3600
    assert "3 times per hour" in str(info.value)
    assert _count(db_session, "pipe_run") == 3


def test_events_older_than_the_window_do_not_count(
    hosted_settings: Settings,
    db_session: Session,
    local_user: User,
) -> None:
    db_session.add_all(
        [
            UsageEvent(
                user_id=local_user.id,
                kind="search",
                created_at=utcnow() - timedelta(hours=1, seconds=1),
            )
            for _ in range(3)
        ]
    )
    db_session.commit()

    quotas.consume(
        db_session,
        user_id=local_user.id,
        kind="search",
        limit=3,
        settings=hosted_settings,
    )

    assert _count(db_session, "search") == 4


def test_quotas_are_per_user(
    hosted_settings: Settings,
    db_session: Session,
    local_user: User,
) -> None:
    other = User(auth0_sub="auth0|other-quota", name="Other")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    for _ in range(3):
        quotas.consume(
            db_session,
            user_id=local_user.id,
            kind="search",
            limit=3,
            settings=hosted_settings,
        )

    quotas.consume(
        db_session,
        user_id=other.id,
        kind="search",
        limit=3,
        settings=hosted_settings,
    )

    assert _count(db_session, "search") == 4


def test_pipe_cap_blocks_the_sixth_pipe(
    hosted_settings: Settings,
    db_session: Session,
    local_user: User,
) -> None:
    for index in range(5):
        db_session.add(Pipe(owner_id=local_user.id, name=f"Pipe {index}"))
    db_session.commit()

    with pytest.raises(quotas.LimitExceeded) as info:
        quotas.ensure_pipe_slot(
            db_session,
            user_id=local_user.id,
            limit=5,
            settings=hosted_settings,
        )

    assert info.value.status_code == 409
    assert "up to 5 pipes" in str(info.value)
    db_session.rollback()


def test_local_api_has_no_pipe_cap_or_run_limit(client: TestClient) -> None:
    created = [
        client.post(
            "/api/pipes",
            json={"name": f"Local pipe {index}", "spec_json": EMPTY_PIPE},
        )
        for index in range(6)
    ]
    assert all(response.status_code == 201 for response in created)
    pipe_id = created[0].json()["id"]

    runs = [client.post(f"/api/pipes/{pipe_id}/run") for _ in range(4)]
    assert all(response.status_code == 200 for response in runs)


def test_local_api_has_no_refresh_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tributary.api.feeds.feeds.refresh_feeds",
        lambda *args, **kwargs: [],
    )

    responses = [client.post("/api/feeds/refresh") for _ in range(11)]
    assert all(response.status_code == 200 for response in responses)


def test_local_api_has_no_search_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tributary.services.search.make_backend",
        lambda *args, **kwargs: FakeBackend(),
    )

    responses = [
        client.post("/api/search", json={"query": f"local query {index}"})
        for index in range(4)
    ]
    assert all(response.status_code == 200 for response in responses)


@pytest.fixture
def cloud_user(cloud_client: TestClient) -> User:
    """Create a cloud user and make every request act as them."""

    with cloud_client.app.state.session_factory() as session:
        user = User(auth0_sub="auth0|quota-user", name="Quota user")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)

    original = dict(cloud_client.app.dependency_overrides)
    cloud_client.app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield user
    finally:
        cloud_client.app.dependency_overrides.clear()
        cloud_client.app.dependency_overrides.update(original)


def test_cloud_pipe_cap(cloud_client: TestClient, cloud_user: User) -> None:
    for index in range(5):
        response = cloud_client.post(
            "/api/pipes",
            json={
                "name": f"Cloud pipe {index}",
                "spec_json": {**EMPTY_PIPE, "name": f"Cloud pipe {index}"},
            },
        )
        assert response.status_code == 201

    response = cloud_client.post(
        "/api/pipes",
        json={"name": "Sixth", "spec_json": EMPTY_PIPE},
    )

    assert response.status_code == 409
    assert "up to 5 pipes" in response.json()["detail"]


def test_cloud_pipe_run_limit(
    cloud_client: TestClient,
    cloud_user: User,
) -> None:
    pipe = cloud_client.post(
        "/api/pipes",
        json={"name": "Limited", "spec_json": EMPTY_PIPE},
    ).json()

    for _ in range(3):
        assert cloud_client.post(f"/api/pipes/{pipe['id']}/run").status_code == 200

    response = cloud_client.post(f"/api/pipes/{pipe['id']}/run")

    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert "3 times per hour" in response.json()["detail"]


def test_cloud_refresh_limit(
    cloud_client: TestClient,
    cloud_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tributary.api.feeds.feeds.refresh_feeds",
        lambda *args, **kwargs: [],
    )

    for _ in range(10):
        assert cloud_client.post("/api/feeds/refresh").status_code == 200

    response = cloud_client.post("/api/feeds/refresh")

    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert "10 times per hour" in response.json()["detail"]


def test_cloud_search_limit_and_cache_hit_is_free(
    cloud_client: TestClient,
    cloud_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(
        "tributary.services.search.make_backend",
        lambda *args, **kwargs: backend,
    )

    for index in range(3):
        response = cloud_client.post(
            "/api/search",
            json={"query": f"cloud query {index}"},
        )
        assert response.status_code == 200

    blocked = cloud_client.post("/api/search", json={"query": "fresh query"})
    assert blocked.status_code == 429
    assert "3 searches per hour" in blocked.json()["detail"]

    cached = cloud_client.post("/api/search", json={"query": "cloud query 0"})
    assert cached.status_code == 200
    assert cached.json()["cached"] is True


def test_cloud_pipe_feed_refresh_counts_as_a_pipe_run(
    cloud_client: TestClient,
    cloud_user: User,
) -> None:
    pipe = cloud_client.post(
        "/api/pipes",
        json={"name": "Pipe feed", "spec_json": EMPTY_PIPE},
    ).json()

    added = cloud_client.post("/api/feeds/pipe", json={"pipe_id": pipe["id"]})
    assert added.status_code == 200
    feed_id = added.json()["feed"]["id"]

    assert cloud_client.post(f"/api/feeds/{feed_id}/refresh").status_code == 200
    assert cloud_client.post(f"/api/feeds/{feed_id}/refresh").status_code == 200

    response = cloud_client.post(f"/api/feeds/{feed_id}/refresh")
    assert response.status_code == 429
    assert "3 times per hour" in response.json()["detail"]
