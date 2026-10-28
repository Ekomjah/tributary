from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from tributary.boxes.ai import MeaningFilterBox, SummarizeBox, WhyCareBox
from tributary.boxes.base import RunContext
from tributary.config import Settings
from tributary.models import Feed, Item
from tributary.schemas import ItemOut
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
        chat=lambda **kwargs: SimpleNamespace(
            message=SimpleNamespace(content="not json")
        )
    )

    with pytest.raises(ModelError, match="valid JSON"):
        client.generate_json("text", schema={"type": "object"})


def test_ollama_client_reports_an_unreachable_server() -> None:
    client = OllamaModelClient(model="gemma3:1b", host="http://test", timeout=1)

    def fail(**kwargs: Any) -> None:
        raise OSError("connection refused")

    client._client = SimpleNamespace(chat=fail)  # type: ignore[assignment]

    with pytest.raises(ModelError, match="http://test"):
        client.generate_json("private text", schema={"type": "object"})
