from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

import sentry_sdk
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import Settings
from .model import ModelClient, ModelError, OllamaModelClient
from .search import SearchError, SearchParams, make_params

logger = logging.getLogger(__name__)

__all__ = [
    "OllamaSearchRefiner",
    "RefinementOutcome",
    "SearchRefiner",
    "SearchSpec",
    "refine_query",
    "sanitize_spec",
]

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_CODE = re.compile(r"^[a-z]{2}$")
_ENGINES = {"google_news", "google"}
_FRESHNESS = {"day", "week", "month", "year"}
_MAX_QUERY = 500
_MAX_RESULTS = 20

_SYSTEM = (
    "You turn a reader's plain-language request into a web search. Rewrite the "
    "request into concise search keywords. Keep names, product names and quoted "
    "phrases. Choose google_news for recent news and google for general web "
    "results. When the request says today, this week, this month or this year, "
    "set freshness to day, week, month or year and keep those time words out of "
    "q. Otherwise set freshness to null. Do not answer the question, add facts "
    "or explain your choices. Reply with JSON only."
)

_FRESHNESS_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(today|tonight|past 24 hours|last 24 hours)\b"), "day"),
    (re.compile(r"\b(this week|past week|last week|weekly)\b"), "week"),
    (re.compile(r"\b(this month|past month|last month|monthly)\b"), "month"),
    (re.compile(r"\b(this year|past year|last year|yearly)\b"), "year"),
]

_TIME_TAIL = re.compile(
    r"\s+(?:today|tonight|past 24 hours|last 24 hours|"
    r"this week|past week|last week|weekly|"
    r"this month|past month|last month|monthly|"
    r"this year|past year|last year|yearly)\s*[.!?]?$",
    re.IGNORECASE,
)


class SearchSpec(BaseModel):
    """The refined search parameters the model is allowed to produce."""

    model_config = ConfigDict(extra="ignore")

    q: str = Field(min_length=1, max_length=_MAX_QUERY)
    engine: Literal["google_news", "google"] = "google_news"
    gl: str = Field(default="us", min_length=2, max_length=5)
    hl: str = Field(default="en", min_length=2, max_length=5)
    freshness: Literal["day", "week", "month", "year"] | None = None
    max_results: int = Field(default=10, ge=1, le=_MAX_RESULTS)


@dataclass(slots=True)
class RefinementOutcome:
    spec: SearchSpec
    fallback: bool
    model: str
    seconds: float

    def to_params(self, settings: Settings) -> SearchParams:
        return make_params(
            settings,
            self.spec.q,
            engine=self.spec.engine,
            gl=self.spec.gl,
            hl=self.spec.hl,
            freshness=self.spec.freshness,
            max_results=self.spec.max_results,
        )


class SearchRefiner(Protocol):
    """Turn a plain-language request into safe SerpAPI parameters."""

    model: str

    def refine(self, query: str) -> RefinementOutcome:
        """Return a refined spec, falling back to the raw query on failure."""


def _clean_query(value: str) -> str:
    return _CONTROL.sub(" ", value).strip()[:_MAX_QUERY]


def _fallback_spec(settings: Settings, query: str) -> SearchSpec:
    return SearchSpec(
        q=_clean_query(query),
        engine=settings.serpapi_engine,
        gl="us",
        hl="en",
        freshness=None,
        max_results=settings.serpapi_max_results,
    )


def _code(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    cleaned = value.strip().lower()
    return cleaned if _CODE.match(cleaned) else default


def _max_results(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(number, _MAX_RESULTS))


def _freshness_hint(query: str) -> str | None:
    """Catch explicit time words when a small model leaves freshness empty."""

    lowered = query.lower()
    for pattern, freshness in _FRESHNESS_HINTS:
        if pattern.search(lowered):
            return freshness
    return None


def _strip_time_tail(query: str) -> str:
    """Move a trailing time phrase into freshness instead of the query.

    The small model sometimes writes ``AI regulation today`` while also setting
    a freshness window. The phrase is redundant there and narrows the search,
    so drop it when a window is present.
    """

    stripped = _TIME_TAIL.sub("", query).strip()
    return stripped or query


def sanitize_spec(
    data: Any,
    *,
    settings: Settings,
    query: str,
) -> SearchSpec:
    """Treat model output as untrusted and coerce it into a safe spec.

    Raises ``ValueError`` when the model did not produce a usable query, so the
    caller can retry and eventually fall back to the raw request.
    """

    if not isinstance(data, dict):
        raise ValueError("the model did not return a JSON object")

    raw_query = data.get("q")
    if not isinstance(raw_query, str):
        raise ValueError("the model did not return a query")

    cleaned = _clean_query(raw_query)
    if not cleaned:
        raise ValueError("the model returned an empty query")

    engine = data.get("engine")
    if engine not in _ENGINES:
        engine = settings.serpapi_engine

    freshness = data.get("freshness")
    if freshness not in _FRESHNESS:
        freshness = _freshness_hint(query)
    if freshness is not None:
        cleaned = _strip_time_tail(cleaned)

    return SearchSpec(
        q=cleaned,
        engine=engine,
        gl=_code(data.get("gl"), "us"),
        hl=_code(data.get("hl"), "en"),
        freshness=freshness,
        max_results=_max_results(data.get("max_results"), settings.serpapi_max_results),
    )


def _prompt(query: str, settings: Settings) -> str:
    return (
        f"Request: {query}\n"
        f"Today: {date.today().isoformat()}\n"
        f"Defaults: engine={settings.serpapi_engine}, gl=us, hl=en, "
        f"max_results={settings.serpapi_max_results}"
    )


@dataclass(slots=True)
class OllamaSearchRefiner:
    """Ask the local model for structured search parameters."""

    settings: Settings
    client: ModelClient

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        client: ModelClient | None = None,
    ) -> OllamaSearchRefiner:
        return cls(
            settings=settings,
            client=client or OllamaModelClient.from_settings(settings),
        )

    @property
    def model(self) -> str:
        return self.client.model

    def refine(self, query: str) -> RefinementOutcome:
        raw = _clean_query(query)
        if not raw:
            raise SearchError("The search query is empty.")

        started = time.perf_counter()
        schema = SearchSpec.model_json_schema()

        with sentry_sdk.start_span(op="search.refine", name=self.model) as span:
            span.set_data("search.refine.model", self.model)
            span.set_data("search.refine.query_length", len(raw))

            for attempt in range(2):
                try:
                    data = self.client.generate_json(
                        _prompt(raw, self.settings),
                        schema=schema,
                        system=_SYSTEM,
                    )
                    spec = sanitize_spec(
                        data,
                        settings=self.settings,
                        query=raw,
                    )
                except (ModelError, ValidationError, ValueError, TypeError) as exc:
                    logger.warning(
                        "Search refinement attempt %s failed: %s",
                        attempt + 1,
                        type(exc).__name__,
                    )
                    continue

                seconds = time.perf_counter() - started
                span.set_data("search.refine.fallback", False)
                span.set_data("search.refine.engine", spec.engine)
                span.set_data("search.refine.freshness", spec.freshness)
                span.set_data("search.refine.max_results", spec.max_results)
                _record_metrics(
                    model=self.model,
                    seconds=seconds,
                    fallback=False,
                )
                return RefinementOutcome(
                    spec=spec,
                    fallback=False,
                    model=self.model,
                    seconds=seconds,
                )

            spec = _fallback_spec(self.settings, raw)
            seconds = time.perf_counter() - started
            span.set_data("search.refine.fallback", True)
            span.set_data("search.refine.engine", spec.engine)
            _record_metrics(
                model=self.model,
                seconds=seconds,
                fallback=True,
            )
            return RefinementOutcome(
                spec=spec,
                fallback=True,
                model=self.model,
                seconds=seconds,
            )


def refine_query(
    settings: Settings,
    query: str,
    *,
    client: ModelClient | None = None,
) -> RefinementOutcome:
    return OllamaSearchRefiner.from_settings(settings, client).refine(query)


def _record_metrics(*, model: str, seconds: float, fallback: bool) -> None:
    try:
        sentry_sdk.metrics.distribution(
            "search.refine.duration",
            seconds * 1000,
            unit="millisecond",
            attributes={"model": model, "fallback": fallback},
        )
        if fallback:
            sentry_sdk.metrics.count(
                "search.refine.fallback",
                1,
                attributes={"model": model},
            )
    except Exception:  # pragma: no cover - telemetry must never break search
        logger.debug("Sentry search refinement metrics failed", exc_info=True)
