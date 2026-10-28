from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..services import refine
from ..services.search import SearchError
from .deps import AppSettings

router = APIRouter(tags=["search"])


class RefineRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("The search query is empty.")
        return cleaned


class RefineOut(BaseModel):
    spec: refine.SearchSpec
    fallback: bool
    model: str
    seconds: float


@router.post("/search/refine", response_model=RefineOut)
def preview_refinement(
    payload: RefineRequest,
    settings: AppSettings,
) -> RefineOut:
    """Preview the search parameters the local model would send to SerpAPI."""

    try:
        outcome = refine.refine_query(settings, payload.query)
    except SearchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RefineOut(
        spec=outcome.spec,
        fallback=outcome.fallback,
        model=outcome.model,
        seconds=round(outcome.seconds, 3),
    )
