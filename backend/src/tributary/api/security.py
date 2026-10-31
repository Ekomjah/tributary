from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Annotated

import jwt
import sentry_sdk
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import ensure_local_user, get_db, utcnow
from ..models import User

_LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=5)
_bearer = HTTPBearer(auto_error=False)


class Auth0Error(RuntimeError):
    """A bearer token could not be trusted."""


@dataclass(frozen=True)
class Auth0Identity:
    sub: str
    email: str | None = None
    name: str | None = None
    email_verified: bool = False


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True)


def clear_jwks_cache() -> None:
    """Clear cached signing keys; used by tests and after tenant changes."""

    _jwks_client.cache_clear()


def _unauthorized(detail: str, error: str | None = None) -> HTTPException:
    challenge = "Bearer"
    if error is not None:
        challenge = f'Bearer error="{error}"'
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": challenge},
    )


def verify_access_token(token: str, settings: Settings) -> Auth0Identity:
    """Validate an Auth0 access token with the tenant's RS256 JWKS."""

    if not settings.auth0_jwks_url or not settings.auth0_audience:
        raise Auth0Error("Auth0 is not configured")

    try:
        signing_key = _jwks_client(settings.auth0_jwks_url).get_signing_key_from_jwt(
            token
        )
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=settings.auth0_issuer,
            leeway=settings.auth0_leeway_seconds,
            options={
                "require": ["exp", "iat", "sub", "iss", "aud"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise Auth0Error("Invalid or expired token") from exc

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise Auth0Error("Token has no subject")

    issued_at = claims.get("iat")
    if isinstance(issued_at, bool) or not isinstance(issued_at, (int, float)):
        raise Auth0Error("Token has no issued-at time")
    if issued_at > time.time() + settings.auth0_leeway_seconds:
        raise Auth0Error("Token was issued in the future")

    email_value = claims.get("email")
    email = email_value.strip().lower() if isinstance(email_value, str) else None
    email_verified = claims.get("email_verified") is True or (
        claims.get("email_verified") == "true"
    )
    name_value = claims.get("name") or claims.get("nickname")
    name = name_value.strip() if isinstance(name_value, str) else None

    return Auth0Identity(
        sub=sub.strip(),
        email=email or None,
        name=name or None,
        email_verified=email_verified,
    )


def _identity_is_allowed(identity: Auth0Identity, settings: Settings) -> bool:
    if not settings.auth0_allowed_subs and not settings.auth0_allowed_emails:
        return True
    if identity.sub in settings.auth0_allowed_subs:
        return True
    return bool(
        identity.email
        and identity.email_verified
        and identity.email in settings.auth0_allowed_emails
    )


def _upsert_user(db: Session, identity: Auth0Identity) -> User:
    now = utcnow()
    user = db.scalar(select(User).where(User.auth0_sub == identity.sub))
    if user is None:
        user = User(
            auth0_sub=identity.sub,
            email=identity.email,
            name=identity.name,
            last_seen_at=now,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent first request created the same subject. Re-read it.
            db.rollback()
            user = db.scalar(select(User).where(User.auth0_sub == identity.sub))
            if user is None:  # pragma: no cover - defensive
                raise
        else:
            db.refresh(user)
        return user

    changed = False
    if identity.email and user.email != identity.email:
        user.email = identity.email
        changed = True
    if identity.name and user.name != identity.name:
        user.name = identity.name
        changed = True
    if (
        user.last_seen_at is None
        or now - user.last_seen_at >= _LAST_SEEN_WRITE_INTERVAL
    ):
        user.last_seen_at = now
        changed = True
    if changed:
        db.commit()
        db.refresh(user)
    return user


def _record_user(user: User) -> None:
    payload: dict[str, str] = {"id": str(user.id)}
    if user.email:
        payload["email"] = user.email
    if user.name:
        payload["username"] = user.name
    sentry_sdk.set_user(payload)


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer),
    ],
) -> User:
    """Identify the caller, creating the local user or upserting an Auth0 one."""

    settings: Settings = request.app.state.settings

    if not settings.is_cloud:
        user = ensure_local_user(db)
    else:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized("Not authenticated")
        try:
            identity = verify_access_token(credentials.credentials, settings)
        except Auth0Error as exc:
            raise _unauthorized("Invalid or expired token", "invalid_token") from exc
        if not _identity_is_allowed(identity, settings):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not invited",
            )
        user = _upsert_user(db, identity)

    request.state.user = user
    _record_user(user)
    return user
