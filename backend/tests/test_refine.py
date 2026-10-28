from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tributary.boxes.base import RunContext
from tributary.boxes.search import SearchBox
from tributary.config import Settings
from tributary.services.model import ModelError
from tributary.services.refine import (
    OllamaSearchRefiner,
    RefinementOutcome,
    SearchSpec,
    sanitize_spec,
)
from tributary.services.search import SearchError, SearchOutcome, SearchParams


class FakeModel:
    model = "fake:1b"

    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.schemas: list[dict[str, Any]] = []
        self.prompts: list[str] = []

    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        self.prompts.append(prompt)
        self.schemas.append(schema)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def make_refiner(settings: Settings, answers: list[Any]) -> tuple[OllamaSearchRefiner, FakeModel]:
    client = FakeModel(answers)
    return OllamaSearchRefiner(settings=settings, client=client), client


def test_refine_returns_structured_spec(settings: Settings) -> None:
    refiner, client = make_refiner(
        settings,
        [
            {
                "q": "AI regulation",
                "engine": "google_news",
                "gl": "us",
                "hl": "en",
                "freshness": "week",
                "max_results": 8,
            }
        ],
    )

    outcome = refiner.refine("AI regulation this week")

    assert outcome.fallback is False
    assert outcome.spec == SearchSpec(
        q="AI regulation",
        engine="google_news",
        gl="us",
        hl="en",
        freshness="week",
        max_results=8,
    )
    assert outcome.model == "fake:1b"
    assert outcome.seconds >= 0
    assert client.calls == 1
    assert client.schemas[0]["properties"]["q"]["maxLength"] == 500
    assert "AI regulation this week" in client.prompts[0]


def test_refine_retries_once_before_succeeding(settings: Settings) -> None:
    refiner, client = make_refiner(
        settings,
        [
            {},
            {
                "q": "databases",
                "engine": "google",
                "max_results": 5,
            },
        ],
    )

    outcome = refiner.refine("databases")

    assert outcome.fallback is False
    assert outcome.spec.q == "databases"
    assert outcome.spec.engine == "google"
    assert client.calls == 2


def test_refine_falls_back_after_two_bad_answers(settings: Settings) -> None:
    refiner, client = make_refiner(settings, [{}, {"q": ""}])

    outcome = refiner.refine("AI regulation this week")

    assert outcome.fallback is True
    assert outcome.spec.q == "AI regulation this week"
    assert outcome.spec.engine == settings.serpapi_engine
    assert outcome.spec.max_results == settings.serpapi_max_results
    assert outcome.spec.freshness is None
    assert client.calls == 2


def test_refine_falls_back_when_ollama_is_unavailable(settings: Settings) -> None:
    refiner, client = make_refiner(
        settings,
        [ModelError("offline"), ModelError("offline")],
    )

    outcome = refiner.refine("local models")

    assert outcome.fallback is True
    assert outcome.spec.q == "local models"
    assert client.calls == 2


def test_refine_falls_back_when_the_model_returns_an_empty_query(
    settings: Settings,
) -> None:
    refiner, _ = make_refiner(settings, [{"q": "   "}, {"q": "\x00\x01"}])

    outcome = refiner.refine("real request")

    assert outcome.fallback is True
    assert outcome.spec.q == "real request"


def test_refine_rejects_an_empty_request(settings: Settings) -> None:
    refiner, client = make_refiner(settings, [])

    with pytest.raises(SearchError):
        refiner.refine("  \x00 ")

    assert client.calls == 0


def test_sanitize_spec_treats_model_output_as_untrusted(
    settings: Settings,
) -> None:
    spec = sanitize_spec(
        {
            "q": "  \x00 AI \n regulation  ",
            "engine": "bing",
            "gl": "USA",
            "hl": "EN",
            "freshness": "decade",
            "max_results": 999,
        },
        settings=settings,
        query="fallback",
    )

    assert spec.q == "AI   regulation"
    assert spec.engine == settings.serpapi_engine
    assert spec.gl == "us"
    assert spec.hl == "en"
    assert spec.freshness is None
    assert spec.max_results == 20


def test_sanitize_spec_infers_an_explicit_time_window(settings: Settings) -> None:
    assert (
        sanitize_spec(
            {"q": "AI regulation"},
            settings=settings,
            query="AI regulation this week",
        ).freshness
        == "week"
    )
    assert (
        sanitize_spec(
            {"q": "AI regulation"},
            settings=settings,
            query="AI regulation today",
        ).freshness
        == "day"
    )
    assert (
        sanitize_spec(
            {"q": "AI regulation"},
            settings=settings,
            query="AI regulation",
        ).freshness
        is None
    )


def test_sanitize_spec_moves_a_trailing_time_word_out_of_the_query(
    settings: Settings,
) -> None:
    spec = sanitize_spec(
        {"q": "AI regulation today", "freshness": "week"},
        settings=settings,
        query="AI regulation this week",
    )

    assert spec.q == "AI regulation"
    assert spec.freshness == "week"

    untouched = sanitize_spec(
        {"q": "databases"},
        settings=settings,
        query="databases",
    )
    assert untouched.q == "databases"
    assert untouched.freshness is None


def test_sanitize_spec_clamps_the_low_end_and_caps_the_query(
    settings: Settings,
) -> None:
    spec = sanitize_spec(
        {"q": "x" * 900, "max_results": 0},
        settings=settings,
        query="fallback",
    )

    assert len(spec.q) == 500
    assert spec.max_results == 1


def test_sanitize_spec_rejects_a_missing_query(settings: Settings) -> None:
    with pytest.raises(ValueError):
        sanitize_spec({"engine": "google"}, settings=settings, query="fallback")

    with pytest.raises(ValueError):
        sanitize_spec(["not", "an", "object"], settings=settings, query="fallback")


class FakeRefiner:
    model = "fake:1b"

    def __init__(self, outcome: RefinementOutcome) -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    def refine(self, query: str) -> RefinementOutcome:
        self.calls.append(query)
        return self.outcome


def make_outcome(
    settings: Settings,
    *,
    q: str = "AI regulation",
    fallback: bool = False,
) -> RefinementOutcome:
    return RefinementOutcome(
        spec=SearchSpec(
            q=q,
            engine="google_news",
            gl="us",
            hl="en",
            freshness="week",
            max_results=7,
        ),
        fallback=fallback,
        model="fake:1b",
        seconds=0.25,
    )


def test_search_box_refines_before_calling_serpapi(
    settings: Settings,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings.model_copy(update={"serpapi_api_key": "dummy"})
    outcome = make_outcome(settings)
    refiner = FakeRefiner(outcome)
    seen: dict[str, SearchParams] = {}

    def fake_run_search(
        session: Session,
        active_settings: Settings,
        params: SearchParams,
        **kwargs: Any,
    ) -> SearchOutcome:
        seen["params"] = params
        return SearchOutcome(
            query=str(kwargs.get("raw_query") or ""),
            params=params,
            items=[],
            cached=False,
            seconds=0.0,
        )

    monkeypatch.setattr(
        "tributary.boxes.search.search.run_search",
        fake_run_search,
    )

    with httpx.Client() as client:
        context = RunContext(
            session=db_session,
            settings=settings,
            client=client,
            refiner=refiner,
        )
        items = SearchBox("AI regulation this week", refine=True).run([], context)

    assert items == []
    assert refiner.calls == ["AI regulation this week"]
    assert seen["params"].q == "AI regulation"
    assert seen["params"].freshness == "week"
    assert seen["params"].max_results == 7
    assert context.sources == [[]]


def test_search_box_can_skip_refinement(
    settings: Settings,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings.model_copy(update={"serpapi_api_key": "dummy"})
    refiner = FakeRefiner(make_outcome(settings))
    seen: dict[str, SearchParams] = {}

    def fake_run_search(
        session: Session,
        active_settings: Settings,
        params: SearchParams,
        **kwargs: Any,
    ) -> SearchOutcome:
        seen["params"] = params
        return SearchOutcome(
            query=str(kwargs.get("raw_query") or ""),
            params=params,
            items=[],
            cached=False,
            seconds=0.0,
        )

    monkeypatch.setattr(
        "tributary.boxes.search.search.run_search",
        fake_run_search,
    )

    with httpx.Client() as client:
        context = RunContext(
            session=db_session,
            settings=settings,
            client=client,
            refiner=refiner,
        )
        SearchBox("raw words", engine="google", max_results=3, refine=False).run(
            [],
            context,
        )

    assert refiner.calls == []
    assert seen["params"].q == "raw words"
    assert seen["params"].engine == "google"
    assert seen["params"].max_results == 3


def test_refine_api_returns_a_preview(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = make_outcome(settings)
    monkeypatch.setattr(
        "tributary.api.refine.refine.refine_query",
        lambda active_settings, query: outcome,
    )

    response = client.post(
        "/api/search/refine",
        json={"query": "AI regulation this week"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["spec"]["q"] == "AI regulation"
    assert body["spec"]["engine"] == "google_news"
    assert body["spec"]["freshness"] == "week"
    assert body["spec"]["max_results"] == 7
    assert body["fallback"] is False
    assert body["model"] == "fake:1b"
    assert body["seconds"] == 0.25


def test_refine_api_returns_fallbacks_with_200(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = make_outcome(settings, q="raw words", fallback=True)
    monkeypatch.setattr(
        "tributary.api.refine.refine.refine_query",
        lambda active_settings, query: outcome,
    )

    response = client.post("/api/search/refine", json={"query": "raw words"})

    assert response.status_code == 200
    assert response.json()["fallback"] is True


def test_refine_api_rejects_a_blank_query(client: TestClient) -> None:
    response = client.post("/api/search/refine", json={"query": "   "})

    assert response.status_code == 422


def test_outcome_builds_search_params(settings: Settings) -> None:
    outcome = OllamaSearchRefiner(
        settings=settings,
        client=FakeModel(
            [
                {
                    "q": "AI regulation",
                    "engine": "google",
                    "gl": "gb",
                    "hl": "en",
                    "freshness": "month",
                    "max_results": 12,
                }
            ]
        ),
    ).refine("AI regulation")

    params = outcome.to_params(settings)

    assert params.q == "AI regulation"
    assert params.engine == "google"
    assert params.gl == "gb"
    assert params.freshness == "month"
    assert params.max_results == 12
