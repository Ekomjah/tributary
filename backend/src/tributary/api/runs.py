from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models import Feed, Item, Pipe, Run
from ..schemas import BoxRunOut, RunOut, RunResultsOut
from .deps import CurrentUser, DbSession
from .ownership import owned_pipe, owned_run

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunOut])
def list_runs(
    user: CurrentUser,
    db: DbSession,
    pipe_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Run]:
    stmt = select(Run).join(Run.pipe).where(Pipe.owner_id == user.id)
    if pipe_id is not None:
        # A foreign pipe ID is indistinguishable from a missing one.
        owned_pipe(db, user.id, pipe_id)
        stmt = stmt.where(Run.pipe_id == pipe_id)
    return list(
        db.scalars(
            stmt.order_by(Run.started.desc(), Run.id.desc()).limit(limit).offset(offset)
        ).all()
    )


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int, user: CurrentUser, db: DbSession) -> Run:
    return owned_run(db, user.id, run_id)


@router.get("/{run_id}/results", response_model=RunResultsOut)
def get_run_results(run_id: int, user: CurrentUser, db: DbSession) -> RunResultsOut:
    """Rebuild a past run's ordered output from its item-id snapshot."""

    run = owned_run(db, user.id, run_id)

    item_ids = list(dict.fromkeys(int(item_id) for item_id in (run.item_ids_json or [])))
    items_by_id: dict[int, Item] = {}
    if item_ids:
        stored = db.scalars(
            select(Item)
            .join(Item.feed)
            .options(selectinload(Item.labels))
            .where(Item.id.in_(item_ids), Feed.owner_id == user.id)
        ).all()
        items_by_id = {item.id: item for item in stored}

    return RunResultsOut(
        run=RunOut.model_validate(run),
        items=[items_by_id[item_id] for item_id in item_ids if item_id in items_by_id],
        steps=[BoxRunOut.model_validate(step) for step in (run.steps_json or [])],
    )
