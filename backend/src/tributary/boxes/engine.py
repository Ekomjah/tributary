from __future__ import annotations

import time
from dataclasses import dataclass, field

import sentry_sdk

from ..schemas import ItemOut
from .ai import MeaningFilterBox, SummarizeBox, WhyCareBox
from .base import Box, BoxError, RunContext
from .plain import (
    DedupeBox,
    FetchBox,
    FilterBox,
    FullTextBox,
    LimitBox,
    MergeBox,
    SortBox,
)
from .search import SearchBox
from .spec import (
    DedupeStep,
    FetchStep,
    FilterStep,
    FullTextStep,
    LimitStep,
    MeaningStep,
    MergeStep,
    PipeSpec,
    SearchStep,
    SortStep,
    SummarizeStep,
    WhyCareStep,
)

__all__ = ["BoxRun", "PipeRunError", "PipeRunResult", "run_pipe"]


@dataclass(slots=True)
class BoxRun:
    box: str
    seconds: float
    items_in: int
    items_out: int
    status: str = "success"
    error: str | None = None


class PipeRunError(BoxError):
    """A step failed, carrying the steps completed before it."""

    def __init__(
        self,
        *,
        step_index: int,
        box: str,
        steps: list[BoxRun],
        cause: BaseException,
    ) -> None:
        self.step_index = step_index
        self.box = box
        self.steps = steps
        self.cause = cause
        super().__init__(f"{box} step failed: {type(cause).__name__}: {cause}")


@dataclass(slots=True)
class PipeRunResult:
    name: str
    items: list[ItemOut]
    seconds: float
    steps: list[BoxRun] = field(default_factory=list)


def _build_box(
    step: FetchStep
    | SearchStep
    | MergeStep
    | DedupeStep
    | FilterStep
    | SortStep
    | LimitStep
    | FullTextStep
    | SummarizeStep
    | MeaningStep
    | WhyCareStep,
) -> Box:
    if isinstance(step, FetchStep):
        return FetchBox(step.urls)
    if isinstance(step, SearchStep):
        return SearchBox(
            step.query,
            engine=step.engine,
            gl=step.gl,
            hl=step.hl,
            freshness=step.freshness,
            max_results=step.max_results,
            refine=step.refine,
        )
    if isinstance(step, MergeStep):
        return MergeBox()
    if isinstance(step, DedupeStep):
        return DedupeBox(step.by)
    if isinstance(step, FilterStep):
        return FilterBox(step.keyword, list(step.fields))
    if isinstance(step, SortStep):
        return SortBox(step.by, step.order)
    if isinstance(step, FullTextStep):
        return FullTextBox()
    if isinstance(step, SummarizeStep):
        return SummarizeBox()
    if isinstance(step, MeaningStep):
        return MeaningFilterBox(step.criterion)
    if isinstance(step, WhyCareStep):
        return WhyCareBox()
    return LimitBox(step.count)


def run_pipe(
    spec: PipeSpec | dict,
    context: RunContext,
) -> PipeRunResult:
    """Execute a validated pipe and return the final item stream."""

    resolved = spec if isinstance(spec, PipeSpec) else PipeSpec.model_validate(spec)
    started = time.perf_counter()
    items: list[ItemOut] = []
    steps: list[BoxRun] = []

    for index, step in enumerate(resolved.steps):
        box = _build_box(step)
        in_count = len(items)
        step_started = time.perf_counter()

        with sentry_sdk.start_span(op="pipe.box", name=step.box) as span:
            span.set_data("pipe.box", step.box)
            span.set_data("pipe.box.index", index)
            span.set_data("pipe.items.in", in_count)
            try:
                items = box.run(items, context)
            except Exception as exc:
                span.set_status("internal_error")
                failed = BoxRun(
                    box=step.box,
                    seconds=time.perf_counter() - step_started,
                    items_in=in_count,
                    items_out=0,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}"[:2000],
                )
                raise PipeRunError(
                    step_index=index,
                    box=step.box,
                    steps=[*steps, failed],
                    cause=exc,
                ) from exc
            span.set_data("pipe.items.out", len(items))

        steps.append(
            BoxRun(
                box=step.box,
                seconds=time.perf_counter() - step_started,
                items_in=in_count,
                items_out=len(items),
            )
        )

    return PipeRunResult(
        name=resolved.name,
        items=items,
        seconds=time.perf_counter() - started,
        steps=steps,
    )
