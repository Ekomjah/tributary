from __future__ import annotations

import logging

from ..schemas import ItemOut
from ..services import search
from .base import BoxError, RunContext

logger = logging.getLogger(__name__)

__all__ = ["SearchBox"]


class SearchBox:
    """Turn a web search into items, using SerpAPI when a key is configured."""

    box = "search"

    def __init__(
        self,
        query: str,
        *,
        engine: str | None = None,
        gl: str | None = None,
        hl: str | None = None,
        freshness: str | None = None,
        max_results: int | None = None,
        refine: bool = False,
    ) -> None:
        self.query = query
        self.engine = engine
        self.gl = gl
        self.hl = hl
        self.freshness = freshness
        self.max_results = max_results
        self.refine = refine

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        if not context.settings.serpapi_api_key:
            logger.warning("Search skipped: SERPAPI_API_KEY is not set; keeping earlier items")
            return items

        try:
            if self.refine:
                refined = context.search_refiner().refine(self.query)
                params = refined.to_params(context.settings)
                logger.info(
                    "Search refined: %r -> %r (%s, fallback=%s)",
                    self.query,
                    params.q,
                    params.engine,
                    refined.fallback,
                )
            else:
                params = search.make_params(
                    context.settings,
                    self.query,
                    engine=self.engine,
                    gl=self.gl,
                    hl=self.hl,
                    freshness=self.freshness,
                    max_results=self.max_results,
                )
            outcome = search.run_search(
                context.session,
                context.settings,
                params,
                raw_query=self.query,
            )
        except search.SearchError as exc:
            raise BoxError(f"search failed: {exc}") from exc

        context.sources.append(outcome.items)
        return outcome.items
