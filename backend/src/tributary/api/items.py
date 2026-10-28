from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import Item, Label
from ..schemas import ArticleFetchOut, Decision, ItemOut, ItemPage, ItemUpdate
from ..services import articles
from .deps import DbSession

router = APIRouter(prefix="/items", tags=["items"])


def _item_query(
    *,
    unread: bool | None,
    starred: bool | None,
    feed_id: int | None,
    label: str | None,
    q: str | None,
    decision: Decision | None,
):
    stmt = select(Item).options(selectinload(Item.labels))
    if unread is not None:
        stmt = stmt.where(Item.is_read.is_(not unread))
    if starred is not None:
        stmt = stmt.where(Item.starred.is_(starred))
    if feed_id is not None:
        stmt = stmt.where(Item.feed_id == feed_id)
    if label:
        stmt = stmt.where(Item.labels.any(Label.name == label))
    if decision is not None:
        stmt = stmt.where(Item.decision == decision)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Item.title.ilike(pattern),
                Item.content.ilike(pattern),
                Item.content_full.ilike(pattern),
            )
        )
    return stmt


@router.get("", response_model=ItemPage)
def list_items(
    db: DbSession,
    unread: bool | None = None,
    starred: bool | None = None,
    feed_id: int | None = None,
    label: str | None = None,
    q: str | None = None,
    decision: Decision | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ItemPage:
    stmt = _item_query(
        unread=unread,
        starred=starred,
        feed_id=feed_id,
        label=label,
        q=q,
        decision=decision,
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(
            Item.published.is_(None),
            Item.published.desc(),
            Item.fetched_at.desc(),
            Item.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return ItemPage(items=list(items), total=total, limit=limit, offset=offset)


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: DbSession) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.post("/{item_id}/fetch", response_model=ArticleFetchOut)
def fetch_item_article(
    item_id: int,
    request: Request,
    db: DbSession,
    force: bool = False,
) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    settings = request.app.state.settings
    with articles.make_client(settings) as client:
        articles.fetch_article(
            db,
            item,
            settings=settings,
            client=client,
            force=force,
        )
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(item_id: int, payload: ItemUpdate, db: DbSession) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    fields = payload.model_fields_set
    if "is_read" in fields and payload.is_read is not None:
        item.is_read = payload.is_read
    if "starred" in fields and payload.starred is not None:
        item.starred = payload.starred
    if "decision" in fields:
        item.decision = payload.decision
    if "label_ids" in fields and payload.label_ids is not None:
        item.labels = _labels_for_ids(db, payload.label_ids)

    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/labels/{label_id}", response_model=ItemOut)
def add_item_label(item_id: int, label_id: int, db: DbSession) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    label = db.get(Label, label_id)
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")

    if label not in item.labels:
        item.labels.append(label)
        db.commit()
        db.refresh(item)
    return item


@router.delete("/{item_id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_label(item_id: int, label_id: int, db: DbSession) -> Response:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    label = db.get(Label, label_id)
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")

    if label in item.labels:
        item.labels.remove(label)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _labels_for_ids(db: Session, label_ids: list[int]) -> list[Label]:
    wanted = sorted(set(label_ids))
    if not wanted:
        return []
    labels = list(db.scalars(select(Label).where(Label.id.in_(wanted))).all())
    found = {label.id for label in labels}
    missing = [str(label_id) for label_id in wanted if label_id not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown label ids: {', '.join(missing)}")
    return labels
