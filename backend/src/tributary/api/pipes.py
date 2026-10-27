from __future__ import annotations

import time

import sentry_sdk
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy import select

from ..boxes import BoxRun, PipeSpec, RunContext, run_pipe
from ..models import Pipe, Run
from ..schemas import BoxRunOut, PipeCreate, PipeOut, PipeRunOut, PipeUpdate, RunOut
from ..services import feeds
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
    db.delete(pipe)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{pipe_id}/run", response_model=PipeRunOut)
def run_saved_pipe(
    pipe_id: int,
    db: DbSession,
    settings: AppSettings,
) -> PipeRunOut:
    pipe = db.get(Pipe, pipe_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail="Pipe not found")

    spec = _validate_spec(pipe.spec_json)
    run = Run(pipe_id=pipe.id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    started = time.perf_counter()

    try:
        with feeds.make_client(settings) as client:
            result = run_pipe(
                spec,
                RunContext(session=db, settings=settings, client=client),
            )
        run = db.get(Run, run_id)
        if run is None:  # pragma: no cover - the row was just committed
            raise RuntimeError("Run record disappeared")
        run.status = "success"
        run.seconds = time.perf_counter() - started
        run.result_count = len(result.items)
        db.commit()
        db.refresh(run)
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "error"
            run.seconds = time.perf_counter() - started
            run.error = f"{type(exc).__name__}: {exc}"[:4000]
            db.commit()
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=422, detail=f"Pipe failed: {exc}") from exc

    return PipeRunOut(
        run=RunOut.model_validate(run),
        items=result.items,
        steps=[_box_run_out(step) for step in result.steps],
    )


def _box_run_out(step: BoxRun) -> BoxRunOut:
    return BoxRunOut(
        box=step.box,
        seconds=step.seconds,
        items_in=step.items_in,
        items_out=step.items_out,
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
