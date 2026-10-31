from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from ..models import Label, normalize_label_name
from ..schemas import LabelCreate, LabelOut
from .deps import CurrentUser, DbSession
from .ownership import owned_label

router = APIRouter(prefix="/labels", tags=["labels"])


@router.get("", response_model=list[LabelOut])
def list_labels(user: CurrentUser, db: DbSession) -> list[Label]:
    return list(
        db.scalars(
            select(Label)
            .where(Label.owner_id == user.id)
            .order_by(Label.name_key)
        ).all()
    )


@router.post("", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
def create_label(
    payload: LabelCreate,
    user: CurrentUser,
    db: DbSession,
) -> Label:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Label name cannot be blank")

    key = normalize_label_name(name)
    existing = db.scalar(
        select(Label).where(Label.owner_id == user.id, Label.name_key == key)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="That label already exists")

    label = Label(owner_id=user.id, name=name)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(label_id: int, user: CurrentUser, db: DbSession) -> Response:
    label = owned_label(db, user.id, label_id)
    db.delete(label)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
