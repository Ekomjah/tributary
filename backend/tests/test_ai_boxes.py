from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import ollama
import pytest
from sentry_sdk.consts import SPANDATA
from sqlalchemy.orm import Session

from tributary.boxes.ai import MeaningFilterBox, SummarizeBox, WhyCareBox
from tributary.boxes.base import RunContext
from tributary.config import Settings
from tributary.models import Feed, Item
from tributary.schemas import ItemOut
from tributary.services import model as model_service
from tributary.services.cache import params_hash
from tributary.services.model import ModelError, OllamaModelClient


class FakeModel:
    model = "fake:1b"

    def __init__(self, answers: list[dict[str, Any]] | None = None) -> None:
        self.answers = list(answers or [])
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any]] = []

    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        if not self.answers:
            raise AssertionError("unexpected model call")
        return self.answers.pop(0)


def seed_item(
    session: Session,
    *,
    title: str,
    content: str = "",
    content_full: str | None = None,
    starred: bool = False,
    decision: str | None = None,
    guid: str | None = None,
) -> Item:
    feed = Feed(url=f"https://example.com/{guid or title}.xml", title="Example")
    session.add(feed)
    session.flush()
    item = Item(
        feed_id=feed.id,
        guid=guid or title,
        title=title,
        link=f"https://example.com/{guid or title}",
        content=content,
        content_full=content_full,
        starred=starred,
        decision=decision,
    )
    session.add(item)
    session.commit()
    return item


def context_for(session: Session, settings: Settings, model: FakeModel) -> RunContext:
    return RunContext(
        session=session,
        settings=settings,
        client=None,  # type: ignore[arg-type]
        model=model,
    )


def test_summarize_skips_items_without_full_text(
    db_session: Session,
    settings: Settings,
) -> None:
    row = seed_item(db_session, title="Stub", content="Short summary.")
    item = ItemOut.model_validate(row)
    model = FakeModel()

    result = SummarizeBox().run([item], context_for(db_session, settings, model))

    assert result[0].summary is None
    assert row.summary is None
    assert model.prompts == []


def test_summarize_stores_the_summary_and_caches_it(
    db_session: Session,
    settings: Settings,
) -> None:
    row = seed_item(
        db_session,
        title="Post",
        content="Short summary.",
        content_full="A long article about Python packaging.",
    )
    item = ItemOut.model_validate(row)
    model = FakeModel([{"summary": "A short article about Python packaging."}])
    context = context_for(db_session, settings, model)

    SummarizeBox().run([item], context)
    assert item.summary == "A short article about Python packaging."
    assert row.summary == item.summary
    assert len(model.prompts) == 1
    assert "A long article" in model.prompts[0]

    again = ItemOut.model_validate(row)
    SummarizeBox().run([again], context)
    assert len(model.prompts) == 1


def test_summarize_cache_misses_when_the_text_changes(
    db_session: Session,
    settings: Settings,
) -> None:
    row = seed_item(
        db_session,
        title="Post",
        content_full="First version of the article.",
    )
    model = FakeModel([{"summary": "First."}, {"summary": "Second."}])
    context = context_for(db_session, settings, model)

    SummarizeBox().run([ItemOut.model_validate(row)], context)
    row.content_full = "Second version of the article."
    db_session.commit()

    result = SummarizeBox().run([ItemOut.model_validate(row)], context)

    assert result[0].summary == "Second."
    assert len(model.prompts) == 2


def test_meaning_filter_keeps_matches_and_items_without_text(
    db_session: Session,
    settings: Settings,
) -> None:
    match = seed_item(
        db_session,
        title="Match",
        content_full="An article about database migrations.",
        guid="match",
    )
    miss = seed_item(
        db_session,
        title="Miss",
        content_full="An article about CSS gradients.",
        guid="miss",
    )
    empty = seed_item(db_session, title="Empty", guid="empty")
    model = FakeModel([{"keep": True, "reason": "yes"}, {"keep": False, "reason": "no"}])
    context = context_for(db_session, settings, model)

    result = MeaningFilterBox("databases").run(
        [
            ItemOut.model_validate(match),
            ItemOut.model_validate(miss),
            ItemOut.model_validate(empty),
        ],
        context,
    )

    assert [item.title for item in result] == ["Match", "Empty"]
    assert len(model.prompts) == 2

    # The same criterion and text is served from the box cache.
    MeaningFilterBox("databases").run([ItemOut.model_validate(match)], context)
    assert len(model.prompts) == 2

    # A different criterion is a different cache key.
    model.answers.append({"keep": False, "reason": "no"})
    MeaningFilterBox("cooking").run([ItemOut.model_validate(match)], context)
    assert len(model.prompts) == 3


def test_why_care_uses_starred_items_and_caches(
    db_session: Session,
    settings: Settings,
) -> None:
    seed_item(
        db_session,
        title="Starred Python post",
        content_full="A starred article.",
        starred=True,
        guid="starred",
    )
    row = seed_item(
        db_session,
        title="New post",
        content_full="An article about type checkers.",
        guid="new",
    )
    model = FakeModel([{"why": "It continues your Python reading."}])
    context = context_for(db_session, settings, model)

    result = WhyCareBox().run([ItemOut.model_validate(row)], context)

    assert result[0].why_care == "It continues your Python reading."
    assert row.why_care == result[0].why_care
    assert "Starred Python post" in model.prompts[0]

    WhyCareBox().run([ItemOut.model_validate(row)], context)
    assert len(model.prompts) == 1


def test_params_hash_is_stable_and_order_independent() -> None:
    assert params_hash(a=1, b="x") == params_hash(b="x", a=1)
    assert params_hash(a=1) != params_hash(a=2)


def test_ollama_client_parses_json_and_hides_prompts() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=lambda **kwargs: SimpleNamespace(
            message=SimpleNamespace(content='{"summary": "Hello."}')
        )
    )

    result = client.generate_json("secret article text", schema={"type": "object"})

    assert result == {"summary": "Hello."}


def test_ollama_client_reports_bad_json() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=lambda **kwargs: SimpleNamespace(message=SimpleNamespace(content="not json"))
    )

    with pytest.raises(ModelError, match="valid JSON"):
        client.generate_json("text", schema={"type": "object"})


def test_ollama_client_reports_an_unreachable_server() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)

    def fail(**kwargs: Any) -> None:
        raise ConnectionError("connection refused")

    client._client = SimpleNamespace(chat=fail)  # type: ignore[assignment]

    with pytest.raises(ModelError, match="Could not reach Ollama at http://test"):
        client.generate_json("private text", schema={"type": "object"})


def test_ollama_client_reports_the_ollama_error_body() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)

    def fail(**kwargs: Any) -> None:
        raise ollama.ResponseError("model 'gemma3:1b' not found", 404)

    client._client = SimpleNamespace(chat=fail)  # type: ignore[assignment]

    with pytest.raises(ModelError) as excinfo:
        client.generate_json("text", schema={"type": "object"})

    message = str(excinfo.value)
    assert "(404)" in message
    assert "model 'gemma3:1b' not found" in message
    assert "Is it running" not in message


def test_ollama_client_reports_a_timeout() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=120)

    def fail(**kwargs: Any) -> None:
        raise httpx.ReadTimeout("timed out")

    client._client = SimpleNamespace(chat=fail)  # type: ignore[assignment]

    with pytest.raises(ModelError, match="did not finish within 120s"):
        client.generate_json("text", schema={"type": "object"})


def test_ollama_client_retries_a_repeat_abort() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)
    calls: list[dict[str, Any]] = []

    def chat(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        if len(calls) == 1:
            raise ollama.ResponseError("prediction aborted, token repeat limit reached", 500)
        return SimpleNamespace(
            message=SimpleNamespace(content='{"why": "It connects to your stars."}')
        )

    client._client = SimpleNamespace(chat=chat)  # type: ignore[assignment]

    result = client.generate_json("text", schema={"type": "object"})

    assert result == {"why": "It connects to your stars."}
    assert len(calls) == 2
    assert calls[0]["options"]["temperature"] == 0
    assert calls[0]["options"]["repeat_penalty"] == 1.1
    assert calls[0]["options"]["repeat_last_n"] == 128
    assert calls[0]["options"]["num_predict"] > 0
    assert calls[1]["options"]["temperature"] == 0.2


def test_ollama_client_stops_after_one_repeat_abort_retry() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)
    calls: list[dict[str, Any]] = []

    def fail(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise ollama.ResponseError("prediction aborted, token repeat limit reached", 500)

    client._client = SimpleNamespace(chat=fail)  # type: ignore[assignment]

    with pytest.raises(ModelError, match="token repeat limit"):
        client.generate_json("text", schema={"type": "object"})

    assert len(calls) == 2


def test_ollama_client_does_not_retry_other_http_errors() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)
    calls: list[dict[str, Any]] = []

    def fail(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise ollama.ResponseError("model 'gemma3:1b' not found", 404)

    client._client = SimpleNamespace(chat=fail)  # type: ignore[assignment]

    with pytest.raises(ModelError, match="not found"):
        client.generate_json("text", schema={"type": "object"})

    assert len(calls) == 1


class FakeSpan:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.status: str | None = None

    def set_data(self, key: str, value: Any) -> None:
        self.data[key] = value

    def set_status(self, value: str) -> None:
        self.status = value

    def __enter__(self) -> FakeSpan:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def test_ollama_client_records_gen_ai_io(monkeypatch) -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=lambda **kwargs: SimpleNamespace(
            message=SimpleNamespace(content='{"summary": "Hello."}'),
            model="gemma3:1b",
            prompt_eval_count=12,
            eval_count=4,
        )
    )
    span = FakeSpan()
    monkeypatch.setattr(
        model_service,
        "get_start_span_function",
        lambda: lambda **kwargs: span,
    )
    monkeypatch.setattr(model_service, "_collect_gen_ai", lambda kind: True)

    result = client.generate_json(
        "secret article text",
        schema={"type": "object"},
        system="Be brief.",
    )

    assert result == {"summary": "Hello."}
    assert json.loads(span.data[SPANDATA.GEN_AI_INPUT_MESSAGES]) == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "secret article text"},
    ]
    assert json.loads(span.data[SPANDATA.GEN_AI_OUTPUT_MESSAGES]) == [
        {"role": "assistant", "content": '{"summary": "Hello."}'}
    ]
    assert span.data[SPANDATA.GEN_AI_REQUEST_MODEL] == "gemma3:1b"
    assert span.data[SPANDATA.GEN_AI_USAGE_INPUT_TOKENS] == 12
    assert span.data[SPANDATA.GEN_AI_USAGE_OUTPUT_TOKENS] == 4
    assert span.data[SPANDATA.GEN_AI_USAGE_TOTAL_TOKENS] == 16


def test_ollama_client_uses_cloud_settings_and_auth_header(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud=True,
        ollama_api_key="cloud-key",
        ollama_model="local:1b",
        ollama_host="http://local:11434",
    )
    captured: dict[str, Any] = {}
    fake_client = SimpleNamespace()

    def make_client(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(model_service.ollama, "Client", make_client)

    client = OllamaModelClient.from_settings(settings)

    assert client.model == "gemma4:3b"
    assert client.host == "https://ollama.com"
    assert captured["host"] == "https://ollama.com"
    assert captured["headers"] == {"Authorization": "Bearer cloud-key"}


def test_ollama_client_uses_local_settings_without_auth(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud=False,
        ollama_api_key="unused-key",
        ollama_model="gemma3:1b",
        ollama_host="http://localhost:11434",
    )
    captured: dict[str, Any] = {}

    def make_client(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(model_service.ollama, "Client", make_client)

    client = OllamaModelClient.from_settings(settings)

    assert client.model == "gemma3:1b"
    assert client.host == "http://localhost:11434"
    assert captured["headers"] == {}


def test_check_ollama_uses_cloud_auth_and_host(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud=True,
        ollama_api_key="cloud-key",
    )
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def list(self) -> SimpleNamespace:
            return SimpleNamespace(
                models=[SimpleNamespace(model="gemma4:3b")]
            )

    monkeypatch.setattr(model_service.ollama, "Client", FakeClient)

    reachable, detail, names = model_service.check_ollama(settings)

    assert reachable is True
    assert detail == "reachable at https://ollama.com"
    assert names == ["gemma4:3b"]
    assert captured["host"] == "https://ollama.com"
    assert captured["headers"] == {"Authorization": "Bearer cloud-key"}


def test_ollama_client_can_omit_gen_ai_content(monkeypatch) -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=lambda **kwargs: SimpleNamespace(
            message=SimpleNamespace(content='{"summary": "Hello."}')
        )
    )
    span = FakeSpan()
    monkeypatch.setattr(
        model_service,
        "get_start_span_function",
        lambda: lambda **kwargs: span,
    )
    monkeypatch.setattr(model_service, "_collect_gen_ai", lambda kind: False)

    client.generate_json("secret article text", schema={"type": "object"})

    assert SPANDATA.GEN_AI_INPUT_MESSAGES not in span.data
    assert SPANDATA.GEN_AI_OUTPUT_MESSAGES not in span.data
    assert span.data[SPANDATA.GEN_AI_OPERATION_NAME] == "chat"
