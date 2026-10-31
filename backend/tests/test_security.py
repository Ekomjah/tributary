from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tributary.api import security
from tributary.api.security import (
    Auth0Error,
    Auth0Identity,
    _identity_is_allowed,
    _record_user,
    _upsert_user,
    verify_access_token,
)
from tributary.config import Settings
from tributary.db import LOCAL_AUTH0_SUB
from tributary.models import User

AUDIENCE = "https://api.example.test"
_ISSUER = "https://tenant.example/"
_AUTH_ENV_KEYS = (
    "AUTH0_DOMAIN",
    "TRIBUTARY_AUTH0_DOMAIN",
    "AUTH0_AUDIENCE",
    "TRIBUTARY_AUTH0_AUDIENCE",
    "AUTH0_CLIENT_ID",
    "TRIBUTARY_AUTH0_CLIENT_ID",
    "AUTH0_ALLOWED_SUBS",
    "TRIBUTARY_AUTH0_ALLOWED_SUBS",
    "AUTH0_ALLOWED_EMAILS",
    "TRIBUTARY_AUTH0_ALLOWED_EMAILS",
)


@pytest.fixture(autouse=True)
def _clean_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _AUTH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(scope="module")
def rsa_private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKS:
    """Stand-in for PyJWKClient so tests never reach the network."""

    def __init__(self, public_key) -> None:
        self.public_key = public_key
        self.error: Exception | None = None
        self.calls = 0

    def get_signing_key_from_jwt(self, token: str):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(key=self.public_key)


@pytest.fixture
def fake_jwks(monkeypatch: pytest.MonkeyPatch, rsa_private_key):
    fake = FakeJWKS(rsa_private_key.public_key())
    monkeypatch.setattr(security, "_jwks_client", lambda _url: fake)
    return fake


@pytest.fixture
def token_settings() -> Settings:
    return Settings(
        _env_file=None,
        auth0_domain="tenant.example",
        auth0_audience=AUDIENCE,
        auth0_client_id="spa-client-id",
    )


def make_token(
    key,
    settings: Settings,
    *,
    algorithm: str = "RS256",
    headers: dict[str, str] | None = None,
    **overrides,
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": "auth0|user-1",
        "iss": settings.auth0_issuer,
        "aud": settings.auth0_audience,
        "iat": now,
        "exp": now + 300,
    }
    for name, value in overrides.items():
        if value is None:
            claims.pop(name, None)
        else:
            claims[name] = value
    return jwt.encode(
        claims,
        key,
        algorithm=algorithm,
        headers=headers or {"kid": "test-key"},
    )


# -- token validation -------------------------------------------------------


def test_valid_token_returns_normalized_identity(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    token = make_token(
        rsa_private_key,
        token_settings,
        email="Ada@Example.com",
        email_verified=True,
        name="  Ada Lovelace  ",
    )

    identity = verify_access_token(token, token_settings)

    assert identity == Auth0Identity(
        sub="auth0|user-1",
        email="ada@example.com",
        name="Ada Lovelace",
        email_verified=True,
    )


def test_nickname_is_used_when_name_is_missing(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    token = make_token(rsa_private_key, token_settings, nickname="ada")

    identity = verify_access_token(token, token_settings)

    assert identity.name == "ada"


def test_expired_token_is_rejected(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    now = int(time.time())
    token = make_token(
        rsa_private_key,
        token_settings,
        iat=now - 600,
        exp=now - 120,
    )

    with pytest.raises(Auth0Error, match="Invalid or expired token"):
        verify_access_token(token, token_settings)


def test_wrong_audience_is_rejected(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    token = make_token(rsa_private_key, token_settings, aud="https://other.example")

    with pytest.raises(Auth0Error):
        verify_access_token(token, token_settings)


def test_wrong_issuer_is_rejected(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    token = make_token(rsa_private_key, token_settings, iss="https://evil.example/")

    with pytest.raises(Auth0Error):
        verify_access_token(token, token_settings)


def test_unsigned_token_is_rejected(
    fake_jwks: FakeJWKS,
    token_settings: Settings,
) -> None:
    token = make_token(None, token_settings, algorithm="none")

    with pytest.raises(Auth0Error):
        verify_access_token(token, token_settings)


def test_hmac_token_is_rejected(
    fake_jwks: FakeJWKS,
    token_settings: Settings,
) -> None:
    token = make_token(
        "not-the-rsa-key-but-long-enough-for-hs256",
        token_settings,
        algorithm="HS256",
    )

    with pytest.raises(Auth0Error):
        verify_access_token(token, token_settings)


def test_token_signed_by_another_key_is_rejected(
    fake_jwks: FakeJWKS,
    token_settings: Settings,
) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(other_key, token_settings)

    with pytest.raises(Auth0Error):
        verify_access_token(token, token_settings)


def test_unknown_signing_key_is_rejected(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    fake_jwks.error = jwt.PyJWKClientError("Unable to find a signing key")
    token = make_token(rsa_private_key, token_settings)

    with pytest.raises(Auth0Error, match="Invalid or expired token"):
        verify_access_token(token, token_settings)


def test_future_issued_at_is_rejected(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    now = int(time.time())
    token = make_token(
        rsa_private_key,
        token_settings,
        iat=now + 120,
        exp=now + 600,
    )

    with pytest.raises(Auth0Error):
        verify_access_token(token, token_settings)


@pytest.mark.parametrize("claim", ["sub", "exp", "iat", "iss", "aud"])
def test_missing_required_claim_is_rejected(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
    claim: str,
) -> None:
    token = make_token(rsa_private_key, token_settings, **{claim: None})

    with pytest.raises(Auth0Error):
        verify_access_token(token, token_settings)


def test_empty_subject_is_rejected(
    fake_jwks: FakeJWKS,
    rsa_private_key,
    token_settings: Settings,
) -> None:
    token = make_token(rsa_private_key, token_settings, sub="   ")

    with pytest.raises(Auth0Error, match="no subject"):
        verify_access_token(token, token_settings)


def test_unconfigured_auth_is_rejected(token_settings: Settings) -> None:
    unconfigured = Settings(
        _env_file=None,
        auth0_audience=AUDIENCE,
        auth0_client_id="spa-client-id",
    )

    with pytest.raises(Auth0Error, match="not configured"):
        verify_access_token("token", unconfigured)


# -- allowlists -------------------------------------------------------------


@pytest.mark.parametrize(
    ("identity", "allowed_subs", "allowed_emails", "expected"),
    [
        (Auth0Identity(sub="auth0|a"), [], [], True),
        (Auth0Identity(sub="auth0|a"), ["auth0|a"], [], True),
        (Auth0Identity(sub="auth0|b"), ["auth0|a"], [], False),
        (
            Auth0Identity(
                sub="auth0|b",
                email="ada@example.com",
                email_verified=True,
            ),
            [],
            ["ada@example.com"],
            True,
        ),
        (
            Auth0Identity(
                sub="auth0|b",
                email="ada@example.com",
                email_verified=False,
            ),
            [],
            ["ada@example.com"],
            False,
        ),
        (
            Auth0Identity(
                sub="auth0|b",
                email="grace@example.com",
                email_verified=True,
            ),
            [],
            ["ada@example.com"],
            False,
        ),
        (
            Auth0Identity(sub="auth0|b", email=None, email_verified=True),
            [],
            ["ada@example.com"],
            False,
        ),
    ],
)
def test_identity_allowlists(
    identity: Auth0Identity,
    allowed_subs: list[str],
    allowed_emails: list[str],
    expected: bool,
) -> None:
    settings = Settings(
        _env_file=None,
        auth0_allowed_subs=allowed_subs,
        auth0_allowed_emails=allowed_emails,
    )

    assert _identity_is_allowed(identity, settings) is expected


# -- user persistence -------------------------------------------------------


def test_init_db_creates_the_local_anchor(engine, session_factory) -> None:
    with session_factory() as session:
        users = session.scalars(select(User)).all()

    assert [user.auth0_sub for user in users] == [LOCAL_AUTH0_SUB]
    assert users[0].name == "Local"


def test_auth0_user_is_upserted_without_duplicates(db_session: Session) -> None:
    first = _upsert_user(
        db_session,
        Auth0Identity(
            sub="auth0|cloud-1",
            email="ada@example.com",
            name="Ada",
            email_verified=True,
        ),
    )
    second = _upsert_user(
        db_session,
        Auth0Identity(
            sub="auth0|cloud-1",
            email="ada@new.example.com",
            name="Ada Lovelace",
            email_verified=True,
        ),
    )

    assert first.id == second.id
    assert second.email == "ada@new.example.com"
    assert second.name == "Ada Lovelace"
    count = db_session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.auth0_sub == "auth0|cloud-1")
    )
    assert count == 1


def test_sentry_user_context_contains_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        security.sentry_sdk,
        "set_user",
        lambda payload: captured.update(payload),
    )
    user = User(
        id=7,
        auth0_sub="auth0|cloud-1",
        email="ada@example.com",
        name="Ada",
    )

    _record_user(user)

    assert captured == {
        "id": "7",
        "email": "ada@example.com",
        "username": "Ada",
    }


# -- local profile ----------------------------------------------------------


def test_local_me_uses_the_internal_user(client: TestClient) -> None:
    first = client.get("/api/me")
    second = client.get("/api/me")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["mode"] == "local"
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["email"] is None


def test_local_me_ignores_any_authorization_header(client: TestClient) -> None:
    response = client.get(
        "/api/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "local"


# -- cloud profile ----------------------------------------------------------


def test_cloud_requires_a_bearer_token(cloud_client: TestClient) -> None:
    response = cloud_client.get("/api/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_cloud_rejects_an_invalid_token(
    cloud_client: TestClient,
    fake_jwks: FakeJWKS,
) -> None:
    fake_jwks.error = jwt.PyJWKClientError("no matching key")

    response = cloud_client.get(
        "/api/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'


def test_cloud_me_creates_the_user_once(
    cloud_client: TestClient,
    cloud_settings: Settings,
    fake_jwks: FakeJWKS,
    rsa_private_key,
) -> None:
    token = make_token(
        rsa_private_key,
        cloud_settings,
        sub="auth0|cloud-1",
        email="ada@example.com",
        email_verified=True,
        name="Ada",
    )
    headers = {"Authorization": f"Bearer {token}"}

    first = cloud_client.get("/api/me", headers=headers)
    second = cloud_client.get("/api/me", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {
        "id": first.json()["id"],
        "email": "ada@example.com",
        "name": "Ada",
        "mode": "cloud",
    }
    assert second.json()["id"] == first.json()["id"]

    engine = cloud_client.app.state.engine
    with Session(engine) as session:
        user = session.scalar(
            select(User).where(User.auth0_sub == "auth0|cloud-1")
        )
        assert user is not None
        assert user.id == first.json()["id"]
        assert user.email == "ada@example.com"


def test_cloud_never_falls_back_to_the_local_anchor(cloud_client: TestClient) -> None:
    engine = cloud_client.app.state.engine
    with Session(engine) as session:
        session.add(User(auth0_sub=LOCAL_AUTH0_SUB, name="Local"))
        session.commit()

    response = cloud_client.get("/api/me")

    assert response.status_code == 401


def test_cloud_sub_allowlist_denies_uninvited_users(
    cloud_client: TestClient,
    cloud_settings: Settings,
    fake_jwks: FakeJWKS,
    rsa_private_key,
) -> None:
    cloud_settings.auth0_allowed_subs = ["auth0|invited"]

    denied = cloud_client.get(
        "/api/me",
        headers={
            "Authorization": "Bearer "
            + make_token(rsa_private_key, cloud_settings, sub="auth0|stranger")
        },
    )
    allowed = cloud_client.get(
        "/api/me",
        headers={
            "Authorization": "Bearer "
            + make_token(rsa_private_key, cloud_settings, sub="auth0|invited")
        },
    )

    assert denied.status_code == 403
    assert denied.json()["detail"] == "This account is not invited"
    assert allowed.status_code == 200
    assert allowed.json()["mode"] == "cloud"


def test_cloud_email_allowlist_requires_a_verified_email(
    cloud_client: TestClient,
    cloud_settings: Settings,
    fake_jwks: FakeJWKS,
    rsa_private_key,
) -> None:
    cloud_settings.auth0_allowed_emails = ["ada@example.com"]

    unverified = cloud_client.get(
        "/api/me",
        headers={
            "Authorization": "Bearer "
            + make_token(
                rsa_private_key,
                cloud_settings,
                sub="auth0|unverified",
                email="ada@example.com",
                email_verified=False,
            )
        },
    )
    wrong_email = cloud_client.get(
        "/api/me",
        headers={
            "Authorization": "Bearer "
            + make_token(
                rsa_private_key,
                cloud_settings,
                sub="auth0|wrong",
                email="grace@example.com",
                email_verified=True,
            )
        },
    )
    allowed = cloud_client.get(
        "/api/me",
        headers={
            "Authorization": "Bearer "
            + make_token(
                rsa_private_key,
                cloud_settings,
                sub="auth0|verified",
                email="ada@example.com",
                email_verified=True,
            )
        },
    )

    assert unverified.status_code == 403
    assert wrong_email.status_code == 403
    assert allowed.status_code == 200

    engine = cloud_client.app.state.engine
    with Session(engine) as session:
        subs = set(session.scalars(select(User.auth0_sub)).all())
    assert "auth0|unverified" not in subs
    assert "auth0|wrong" not in subs
    assert "auth0|verified" in subs


def test_cloud_disables_docs_and_keeps_health_public(cloud_client: TestClient) -> None:
    assert cloud_client.get("/docs").status_code == 404
    assert cloud_client.get("/redoc").status_code == 404
    assert cloud_client.get("/openapi.json").status_code == 404

    root = cloud_client.get("/")
    assert root.status_code == 200
    assert root.json()["docs"] is None

    assert cloud_client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/api/me", "/api/feeds", "/api/items", "/api/labels", "/api/pipes"],
)
def test_cloud_protects_every_api_router(cloud_client: TestClient, path: str) -> None:
    assert cloud_client.get(path).status_code == 401
