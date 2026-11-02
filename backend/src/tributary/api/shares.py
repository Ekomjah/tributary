from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from ..models import Share
from ..schemas import (
    FeedOut,
    ItemOut,
    ShareClaimOut,
    ShareLinkOut,
    SharePreviewOut,
)
from ..services import shares
from .deps import CurrentUser, DbSession
from .ownership import owned_item

router = APIRouter(tags=["shares"])


def _load_share(db: Session, token: str) -> Share:
    try:
        return shares.find_share(db, token)
    except shares.ShareNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This share link is invalid or has expired.",
        ) from exc


@router.post(
    "/items/{item_id}/share-link",
    response_model=ShareLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_share_link(
    item_id: int,
    user: CurrentUser,
    db: DbSession,
) -> ShareLinkOut:
    item = owned_item(db, user.id, item_id)
    share, token = shares.create_share(db, item, user)
    db.commit()
    return ShareLinkOut(token=token, expires_at=share.expires_at)


@router.get("/shares/{token}", response_model=SharePreviewOut)
def preview_share(token: str, user: CurrentUser, db: DbSession) -> SharePreviewOut:
    share = _load_share(db, token)
    try:
        preview = shares.preview_share(share, user)
    except shares.ShareExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This share link has expired.",
        ) from exc
    return SharePreviewOut(**preview)


@router.post("/shares/{token}/claim", response_model=ShareClaimOut)
def claim_share(token: str, user: CurrentUser, db: DbSession) -> ShareClaimOut:
    share = _load_share(db, token)
    try:
        result = shares.claim_share(db, share, user)
    except shares.ShareExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This share link has expired.",
        ) from exc
    except shares.OwnShareLink as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This is your own share link. Send it to someone else.",
        ) from exc
    except shares.ShareAlreadyClaimed as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This share link has already been claimed.",
        ) from exc

    db.commit()
    db.refresh(result.item)
    db.refresh(result.feed)
    return ShareClaimOut(
        item=ItemOut.model_validate(result.item),
        feed=FeedOut.model_validate(result.feed),
        already_claimed=result.already_claimed,
    )
