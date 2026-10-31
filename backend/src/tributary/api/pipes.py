from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select

from ..boxes import PipeSpec
from ..models import Feed, Pipe, Run
from ..schemas import PipeCreate, PipeOut, PipeRunOut, PipeUpdate, RunOut
from ..services import pipe_runs
from .deps import AppSettings, CurrentUser, DbSession
from .ownership import owned_pipe

router = APIRouter(prefix="/pipes", tags=["pipes"])


@router.get("", response_model=list[PipeOut])
def list_pipes(user: CurrentUser, db: DbSession) -> list[Pipe]:
    return list(
        db.scalars(
            select(Pipe)
            .where(Pipe.owner_id == user.id)
            .order_by(Pipe.updated_at.desc(), Pipe.id.desc())
        ).all()
    )


@router.post("", response_model=PipeOut, status_code=status.HTTP_201_CREATED)
def create_pipe(
    payload: PipeCreate,
    user: CurrentUser,
    db: DbSession,
) -> Pipe:
    spec = _validate_spec(payload.spec_json)
    pipe = Pipe(
        owner_id=user.id,
        name=(payload.name or spec.name).strip()[:200],
        spec_json=payload.spec_json,
    )
    db.add(pipe)
    db.commit()
    db.refresh(pipe)
    return pipe


@router.get("/{pipe_id}", response_model=PipeOut)
def get_pipe(pipe_id: int, user: CurrentUser, db: DbSession) -> Pipe:
    pipe = owned_pipe(db, user.id, pipe_id)
    return pipe


@router.patch("/{pipe_id}", response_model=PipeOut)
def update_pipe(
    pipe_id: int,
    payload: PipeUpdate,
    user: CurrentUser,
    db: DbSession,
) -> Pipe:
    pipe = owned_pipe(db, user.id, pipe_id)

    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        pipe.name = payload.name.strip()[:200]
        linked_feed = db.scalar(
            select(Feed).where(Feed.pipe_id == pipe.id, Feed.owner_id == user.id)
        )
        if linked_feed is not None:
            linked_feed.title = pipe.name[:500]
    if "spec_json" in fields and payload.spec_json is not None:
        _validate_spec(payload.spec_json)
        pipe.spec_json = payload.spec_json

    db.commit()
    db.refresh(pipe)
    return pipe


@router.delete("/{pipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pipe(pipe_id: int, user: CurrentUser, db: DbSession) -> Response:
    pipe = owned_pipe(db, user.id, pipe_id)
    # Older SQLite databases have no ON DELETE CASCADE on feeds.pipe_id, so
    # remove the reader feed explicitly before the pipe row goes away.
    linked_feed = db.scalar(
        select(Feed).where(Feed.pipe_id == pipe.id, Feed.owner_id == user.id)
    )
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
    user: CurrentUser,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> Run:
    """Start a pipe run on a worker and return the running record."""

    pipe = owned_pipe(db, user.id, pipe_id)

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
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> PipeRunOut:
    pipe = owned_pipe(db, user.id, pipe_id)

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
