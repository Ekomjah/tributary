from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas import SearchOut, SearchRequest
from ..services import search
from .deps import AppSettings, DbSession

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchOut)
def run_web_search(
    payload: SearchRequest,
    db: DbSession,
    settings: AppSettings,
) -> SearchOut:
    """Run a web search and store the results as a virtual search feed."""

    try:
        params = search.make_params(
            settings,
            payload.query,
            engine=payload.engine,
            gl=payload.gl,
            hl=payload.hl,
            freshness=payload.freshness,
            max_results=payload.max_results,
        )
        outcome = search.run_search(
            db,
            settings,
            params,
            raw_query=payload.query,
        )
    except search.SearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    db.commit()
    return SearchOut(
        query=outcome.query,
        q=outcome.params.q,
        engine=outcome.params.engine,
        freshness=outcome.params.freshness,
        cached=outcome.cached,
        seconds=round(outcome.seconds, 3),
        items=outcome.items,
    )
