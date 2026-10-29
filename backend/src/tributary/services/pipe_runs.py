from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import httpx
import sentry_sdk
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..boxes import BoxRun, PipeRunError, PipeSpec, RunContext, run_pipe
from ..config import Settings
from ..models import Pipe, Run
from ..schemas import BoxRunOut, ItemOut
from . import feeds

__all__ = [
    "PipeExecution",
    "begin_run",
    "execute_pipe",
    "execute_run",
    "launch_run",
    "reap_interrupted_runs",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipeExecution:
    """The outcome of one pipe run, including the persisted run record."""

    run: Run | None
    items: list[ItemOut] = field(default_factory=list)
    steps: list[BoxRunOut] = field(default_factory=list)
    item_ids: list[int] = field(default_factory=list)
    error: str | None = None


def begin_run(session: Session, pipe_id: int) -> Run:
    """Create and commit a running run row before any work starts."""

    run = Run(pipe_id=pipe_id, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def execute_pipe(
    session: Session,
    settings: Settings,
    pipe: Pipe,
    *,
    client: httpx.Client | None = None,
) -> PipeExecution:
    """Run a saved pipe synchronously and persist its result."""

    run = begin_run(session, pipe.id)
    return execute_run(session, settings, pipe, run.id, client=client)


def execute_run(
    session: Session,
    settings: Settings,
    pipe: Pipe,
    run_id: int,
    *,
    client: httpx.Client | None = None,
) -> PipeExecution:
    """Run a pipe against an existing run row and record the outcome.

    A failed step is persisted in ``steps_json`` with its status and error, and
    its zero-based position and box name are copied onto the run row so the UI
    can point at the box that broke.
    """

    started = time.perf_counter()
    owns_client = client is None
    active_client = client
    try:
        if active_client is None:
            active_client = feeds.make_client(settings)

        spec = PipeSpec.model_validate(pipe.spec_json)
        result = run_pipe(
            spec,
            RunContext(session=session, settings=settings, client=active_client),
        )
        run = session.get(Run, run_id)
        if run is None:
            return PipeExecution(run=None, error="The run record no longer exists.")

        item_ids = _unique_item_ids(result.items)
        run.status = "success"
        run.seconds = time.perf_counter() - started
        run.result_count = len(item_ids)
        run.steps_json = [_step_dict(step) for step in result.steps]
        run.item_ids_json = item_ids
        run.error = None
        run.error_step = None
        run.error_box = None
        session.commit()
        session.refresh(run)

        return PipeExecution(
            run=run,
            items=result.items,
            steps=[_box_run_out(step) for step in result.steps],
            item_ids=item_ids,
        )
    except PipeRunError as exc:
        session.rollback()
        message = str(exc)[:4000]
        run = _mark_run_error(
            session,
            run_id,
            message,
            seconds=time.perf_counter() - started,
            steps=[_step_dict(step) for step in exc.steps],
            error_step=exc.step_index,
            error_box=exc.box,
        )
        sentry_sdk.capture_exception(exc)
        return PipeExecution(
            run=run,
            steps=[_box_run_out(step) for step in exc.steps],
            error=message,
        )
    except Exception as exc:
        session.rollback()
        message = f"{type(exc).__name__}: {exc}"[:4000]
        run = _mark_run_error(
            session,
            run_id,
            message,
            seconds=time.perf_counter() - started,
        )
        sentry_sdk.capture_exception(exc)
        return PipeExecution(run=run, error=message)
    finally:
        if owns_client and active_client is not None:
            active_client.close()


def launch_run(
    session_factory: sessionmaker[Session],
    settings: Settings,
    pipe_id: int,
    run_id: int,
) -> None:
    """Start a run on a daemon worker and return immediately."""

    thread = threading.Thread(
        target=_run_in_thread,
        args=(session_factory, settings, pipe_id, run_id),
        name=f"pipe-run-{run_id}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception as exc:
        with session_factory() as session:
            _mark_run_error(
                session,
                run_id,
                f"Could not start the run: {type(exc).__name__}: {exc}"[:4000],
            )
        sentry_sdk.capture_exception(exc)
        raise


def _run_in_thread(
    session_factory: sessionmaker[Session],
    settings: Settings,
    pipe_id: int,
    run_id: int,
) -> None:
    try:
        with session_factory() as session:
            pipe = session.get(Pipe, pipe_id)
            if pipe is None:
                _mark_run_error(
                    session,
                    run_id,
                    "The pipe was deleted before the run started.",
                )
                return
            execute_run(session, settings, pipe, run_id)
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        sentry_sdk.capture_exception(exc)
        logger.exception("Pipe run %s crashed", run_id)
        try:
            with session_factory() as session:
                _mark_run_error(
                    session,
                    run_id,
                    f"{type(exc).__name__}: {exc}"[:4000],
                )
        except Exception:
            logger.exception("Could not record the failure of pipe run %s", run_id)


def reap_interrupted_runs(session_factory: sessionmaker[Session]) -> int:
    """Mark runs left running by a previous process as failed.

    Runs live in daemon threads, so a restart cannot resume them. Without this
    sweep a crashed or restarted server leaves rows stuck on ``running``.
    """

    with session_factory() as session:
        runs = list(session.scalars(select(Run).where(Run.status == "running")).all())
        for run in runs:
            run.status = "error"
            run.error = "The run was interrupted before it finished. Start it again."
            run.error_step = None
            run.error_box = None
            run.result_count = 0
            run.seconds = None
        session.commit()
        return len(runs)


def _mark_run_error(
    session: Session,
    run_id: int,
    message: str,
    *,
    seconds: float | None = None,
    steps: list[dict[str, object]] | None = None,
    error_step: int | None = None,
    error_box: str | None = None,
) -> Run | None:
    run = session.get(Run, run_id)
    if run is None or run.status != "running":
        return run

    run.status = "error"
    run.seconds = seconds
    run.error = message
    run.error_step = error_step
    run.error_box = error_box
    run.result_count = 0
    run.steps_json = steps or []
    run.item_ids_json = []
    session.commit()
    session.refresh(run)
    return run


def _unique_item_ids(items: list[ItemOut]) -> list[int]:
    seen: set[int] = set()
    ids: list[int] = []
    for item in items:
        if item.id <= 0 or item.id in seen:
            continue
        seen.add(item.id)
        ids.append(item.id)
    return ids


def _step_dict(step: BoxRun) -> dict[str, object]:
    return {
        "box": step.box,
        "seconds": step.seconds,
        "items_in": step.items_in,
        "items_out": step.items_out,
        "status": step.status,
        "error": step.error,
    }


def _box_run_out(step: BoxRun) -> BoxRunOut:
    return BoxRunOut(
        box=step.box,
        seconds=step.seconds,
        items_in=step.items_in,
        items_out=step.items_out,
        status="error" if step.status == "error" else "success",
        error=step.error,
    )
