from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select

from ..boxes import PipeSpec
from ..models import Feed, Pipe, Run
from ..schemas import PipeCreate, PipeOut, PipeRunOut, PipeUpdate, RunOut
from ..services import pipe_runs
from .deps import AppSettings, DbSession

router = APIRouter(prefix="/pipes", tags=["pipes"])


@router.get("", response_model=list[PipeOut])
def list_pipes(db: DbSession) -> list[Pipe]:
    return list(db.scalars(select(Pipe).order_by(Pipe.updated_at.desc(), Pipe.id.desc())).all())


@router.post("", response_model=PipeOut, status_code=status.HTTP_201_CREATED)
def create_pipe(payload: PipeCreate, db: DbSession) -> Pipe:
    spec = _validate_spec(payload.spec_json)
    pipe = Pipe(
        name=(payload.name or spec.name).strip()[:200],
        spec_json=payload.spec_json,
    )
    db.add(pipe)
    db.commit()
    db.refresh(pipe)
    return pipe


@router.get("/{pipe_id}", response_model=PipeOut)
def get_pipe(pipe_id: int, db: DbSession) -> Pipe:
    pipe = db.get(Pipe, pipe_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail="Pipe not found")
    return pipe


@router.patch("/{pipe_id}", response_model=PipeOut)
def update_pipe(pipe_id: int, payload: PipeUpdate, db: DbSession) -> Pipe:
    pipe = db.get(Pipe, pipe_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail="Pipe not found")

    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        pipe.name = payload.name.strip()[:200]
        linked_feed = db.scalar(select(Feed).where(Feed.pipe_id == pipe.id))
        if linked_feed is not None:
            linked_feed.title = pipe.name[:500]
    if "spec_json" in fields and payload.spec_json is not None:
        _validate_spec(payload.spec_json)
        pipe.spec_json = payload.spec_json

    db.commit()
    db.refresh(pipe)
    return pipe


@router.delete("/{pipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pipe(pipe_id: int, db: DbSession) -> Response:
    pipe = db.get(Pipe, pipe_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail="Pipe not found")
    # Older SQLite databases have no ON DELETE CASCADE on feeds.pipe_id, so
    # remove the reader feed explicitly before the pipe row goes away.
    linked_feed = db.scalar(select(Feed).where(Feed.pipe_id == pipe.id))
    if linked_feed is not None:
        db.delete(linked_feed)
    db.delete(pipe)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{pipe_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_pipe_run(
    pipe_id: int,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> Run:
    """Start a pipe run on a worker and return the running record."""

    pipe = db.get(Pipe, pipe_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail="Pipe not found")

    run = pipe_runs.begin_run(db, pipe.id)
    pipe_runs.launch_run(
        request.app.state.session_factory,
        settings,
        pipe.id,
        run.id,
    )
    return run


@router.post("/{pipe_id}/run", response_model=PipeRunOut)
def run_saved_pipe(
    pipe_id: int,
    db: DbSession,
    settings: AppSettings,
) -> PipeRunOut:
    pipe = db.get(Pipe, pipe_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail="Pipe not found")

    execution = pipe_runs.execute_pipe(db, settings, pipe)
    if execution.error or execution.run is None:
        raise HTTPException(
            status_code=422,
            detail=f"Pipe failed: {execution.error}",
        )

    return PipeRunOut(
        run=RunOut.model_validate(execution.run),
        items=execution.items,
        steps=execution.steps,
    )


def _validate_spec(spec_json: dict) -> PipeSpec:
    try:
        return PipeSpec.model_validate(spec_json)
    except ValidationError as exc:
        detail = [
            {"loc": list(error["loc"]), "msg": error["msg"]}
            for error in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=detail) from exc
