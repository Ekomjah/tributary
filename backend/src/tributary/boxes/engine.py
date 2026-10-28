from __future__ import annotations

import time
from dataclasses import dataclass, field

import sentry_sdk

from ..schemas import ItemOut
from .base import Box, RunContext
from .plain import (
    DedupeBox,
    FetchBox,
    FilterBox,
    FullTextBox,
    LimitBox,
    MergeBox,
    SortBox,
)
from .spec import (
    DedupeStep,
    FetchStep,
    FilterStep,
    FullTextStep,
    LimitStep,
    MergeStep,
    PipeSpec,
    SortStep,
)

__all__ = ["BoxRun", "PipeRunResult", "run_pipe"]


@dataclass(slots=True)
class BoxRun:
    box: str
    seconds: float
    items_in: int
    items_out: int


@dataclass(slots=True)
class PipeRunResult:
    name: str
    items: list[ItemOut]
    seconds: float
    steps: list[BoxRun] = field(default_factory=list)


def _build_box(
    step: FetchStep
    | MergeStep
    | DedupeStep
    | FilterStep
    | SortStep
    | LimitStep
    | FullTextStep,
) -> Box:
    if isinstance(step, FetchStep):
        return FetchBox(step.urls)
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
            except Exception:
                span.set_status("internal_error")
                raise
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
