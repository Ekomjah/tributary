from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..models import Run
from ..schemas import RunOut
from .deps import DbSession

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunOut])
def list_runs(
    db: DbSession,
    pipe_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Run]:
    stmt = select(Run)
    if pipe_id is not None:
        stmt = stmt.where(Run.pipe_id == pipe_id)
    return list(
        db.scalars(
            stmt.order_by(Run.started.desc(), Run.id.desc()).limit(limit).offset(offset)
        ).all()
    )


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: DbSession) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
