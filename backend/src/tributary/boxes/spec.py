from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

FilterField = Literal["title", "content", "link"]


class PipeSpecError(ValueError):
    """A pipe file is missing, unreadable or invalid."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FetchStep(StrictModel):
    box: Literal["fetch"]
    urls: list[str] = Field(min_length=1)


class MergeStep(StrictModel):
    box: Literal["merge"]


class DedupeStep(StrictModel):
    box: Literal["dedupe"]
    by: Literal["link", "guid", "title"] = "link"


class FilterStep(StrictModel):
    box: Literal["filter"]
    keyword: str = Field(min_length=1, max_length=500)
    fields: list[FilterField] = Field(
        default_factory=lambda: ["title", "content"],
        min_length=1,
    )


class SortStep(StrictModel):
    box: Literal["sort"]
    by: Literal["published", "fetched_at", "title"] = "published"
    order: Literal["asc", "desc"] = "desc"


class LimitStep(StrictModel):
    box: Literal["limit"]
    count: int = Field(default=10, ge=1, le=500)


class FullTextStep(StrictModel):
    box: Literal["fulltext"]


PipeStep = Annotated[
    FetchStep
    | MergeStep
    | DedupeStep
    | FilterStep
    | SortStep
    | LimitStep
    | FullTextStep,
    Field(discriminator="box"),
]


class PipeSpec(StrictModel):
    name: str = Field(default="", max_length=200)
    steps: list[PipeStep] = Field(min_length=1)


def load_pipe_spec(path: Path) -> PipeSpec:
    """Read and validate a pipe JSON file."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipeSpecError(f"Could not read {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PipeSpecError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise PipeSpecError(f"{path} must contain a JSON object")

    try:
        return PipeSpec.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise PipeSpecError(f"{path} is not a valid pipe: {details}") from exc
