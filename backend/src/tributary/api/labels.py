from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from ..models import Label
from ..schemas import LabelCreate, LabelOut
from .deps import DbSession

router = APIRouter(prefix="/labels", tags=["labels"])


@router.get("", response_model=list[LabelOut])
def list_labels(db: DbSession) -> list[Label]:
    return list(db.scalars(select(Label).order_by(Label.name)).all())


@router.post("", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
def create_label(payload: LabelCreate, db: DbSession) -> Label:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Label name cannot be blank")

    existing = db.scalar(select(Label).where(Label.name == name))
    if existing is not None:
        raise HTTPException(status_code=409, detail="That label already exists")

    label = Label(name=name)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(label_id: int, db: DbSession) -> Response:
    label = db.get(Label, label_id)
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")
    db.delete(label)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
