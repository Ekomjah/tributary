from __future__ import annotations

from fastapi import APIRouter

from ..schemas import MeOut
from .deps import AppSettings, CurrentUser

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeOut)
def me(user: CurrentUser, settings: AppSettings) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        mode="cloud" if settings.is_cloud else "local",
    )
