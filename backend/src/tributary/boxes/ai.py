from __future__ import annotations

import logging
import time
from typing import Any

import sentry_sdk
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Feed, Item
from ..schemas import ItemOut
from ..services import cache
from .base import RunContext

logger = logging.getLogger(__name__)

__all__ = [
    "MeaningFilterBox",
    "SummarizeBox",
    "WhyCareBox",
]

SUMMARY_PROMPT_VERSION = "summarize-v1"
MEANING_PROMPT_VERSION = "meaning-v1"
WHY_CARE_PROMPT_VERSION = "whycare-v1"

_TEXT_LIMIT = 8000
_OUTPUT_LIMIT = 500
_STARRED_LIMIT = 20


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="One sentence, at most 30 words.")


class MeaningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep: bool = Field(description="Whether the article matches the criterion.")
    reason: str = Field(description="A short reason for the decision.")


class WhyCareOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    why: str = Field(description="One sentence about why this reader might care.")


def _row_and_text(
    session: Session,
    item: ItemOut,
    *,
    full_only: bool,
) -> tuple[Item | None, str]:
    row = session.get(Item, item.id)
    full = (row.content_full if row is not None else item.content_full) or ""
    if full_only:
        text = full
    else:
        text = full or (row.content if row is not None else item.content) or ""
    return row, text.strip()[:_TEXT_LIMIT]


def _ask(
    context: RunContext,
    row: Item | None,
    *,
    box: str,
    params: str,
    prompt: str,
    schema: dict[str, Any],
    system: str,
) -> dict[str, Any]:
    client = context.model_client()

    if row is not None:
        cached = cache.get_cached(
            context.session,
            item_id=row.id,
            box=box,
            params_hash=params,
            model=client.model,
        )
        if cached is not None:
            return cached

    started = time.perf_counter()
    with sentry_sdk.start_span(op="ai.generate", name=box) as span:
        span.set_data("ai.box", box)
        span.set_data("ai.model", client.model)
        try:
            output = client.generate_json(prompt, schema=schema, system=system)
        except Exception:
            span.set_status("internal_error")
            _record_metrics(box, client.model, started, status="error")
            raise
        span.set_data("ai.duration_ms", round((time.perf_counter() - started) * 1000, 1))
        _record_metrics(box, client.model, started, status="ok")

    if row is not None:
        cache.set_cached(
            context.session,
            item_id=row.id,
            box=box,
            params_hash=params,
            model=client.model,
            output=output,
        )
    return output


def _record_metrics(box: str, model: str, started: float, *, status: str) -> None:
    try:
        elapsed_ms = (time.perf_counter() - started) * 1000
        sentry_sdk.metrics.count(
            "ai.calls",
            1,
            attributes={"box": box, "model": model, "status": status},
        )
        sentry_sdk.metrics.distribution(
            "ai.duration",
            elapsed_ms,
            unit="millisecond",
            attributes={"box": box, "model": model, "status": status},
        )
    except Exception:  # pragma: no cover - telemetry must never break a pipe
        logger.debug("Sentry AI metrics failed", exc_info=True)


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()[:_OUTPUT_LIMIT]
    return text or None


class SummarizeBox:
    """Write a one-line summary for each item that has full text."""

    box = "summarize"

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        for item in items:
            row, text = _row_and_text(context.session, item, full_only=True)
            if not text:
                # Extraction failed or has not run. Do not summarize the stub.
                continue

            params = cache.params_hash(
                version=SUMMARY_PROMPT_VERSION,
                content=cache.content_hash(text),
            )
            output = _ask(
                context,
                row,
                box=self.box,
                params=params,
                prompt=_summary_prompt(item, text),
                schema=SummaryOutput.model_json_schema(),
                system=(
                    "You summarize articles for a feed reader. Reply with one sentence "
                    "of at most 30 words, in the article's language. Use only facts "
                    "that appear in the text."
                ),
            )
            summary = _clean(output.get("summary"))
            item.summary = summary
            if row is not None:
                row.summary = summary

        context.session.flush()
        return items


class MeaningFilterBox:
    """Keep items that match a plain-language criterion, judged locally."""

    box = "meaning"

    def __init__(self, criterion: str) -> None:
        self.criterion = criterion.strip()

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        kept: list[ItemOut] = []

        for item in items:
            row, text = _row_and_text(context.session, item, full_only=False)
            if not text:
                # No text to judge. Keep it rather than silently losing items.
                kept.append(item)
                continue

            params = cache.params_hash(
                version=MEANING_PROMPT_VERSION,
                criterion=self.criterion,
                content=cache.content_hash(text),
            )
            output = _ask(
                context,
                row,
                box=self.box,
                params=params,
                prompt=_meaning_prompt(self.criterion, item, text),
                schema=MeaningOutput.model_json_schema(),
                system=(
                    "You filter articles for a reader. Decide whether the article "
                    "matches the criterion. Be strict and do not stretch the meaning. "
                    "Reply with JSON only."
                ),
            )
            if bool(output.get("keep")):
                kept.append(item)

        context.session.flush()
        return kept


class WhyCareBox:
    """Explain why an item might matter, learned from the reader's stars."""

    box = "whycare"

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        stmt = (
            select(Item.title)
            .join(Item.feed)
            .where(Item.starred.is_(True), Feed.owner_id == context.owner_id)
            .order_by(Item.id.desc())
            .limit(_STARRED_LIMIT)
        )
        starred = [
            title
            for title in context.session.scalars(stmt)
            if title
        ]
        taste = "\n".join(f"- {title}" for title in starred)
        taste_hash = cache.content_hash(taste)

        for item in items:
            row, text = _row_and_text(context.session, item, full_only=False)
            if not text:
                continue

            params = cache.params_hash(
                version=WHY_CARE_PROMPT_VERSION,
                content=cache.content_hash(text),
                taste=taste_hash,
            )
            output = _ask(
                context,
                row,
                box=self.box,
                params=params,
                prompt=_why_prompt(item, text, taste),
                schema=WhyCareOutput.model_json_schema(),
                system=(
                    "Explain in one sentence why this article might matter to this "
                    "reader, using only the article and the list of starred titles. "
                    "If there is no clear connection, say so plainly."
                ),
            )
            why = _clean(output.get("why"))
            item.why_care = why
            if row is not None:
                row.why_care = why

        context.session.flush()
        return items


def _summary_prompt(item: ItemOut, text: str) -> str:
    return f"Title: {item.title}\n\n{text}"


def _meaning_prompt(criterion: str, item: ItemOut, text: str) -> str:
    return f"Criterion: {criterion}\nTitle: {item.title}\n\n{text}"


def _why_prompt(item: ItemOut, text: str, taste: str) -> str:
    return (
        "Reader's starred articles:\n"
        f"{taste or '(none yet)'}\n\n"
        f"Article title: {item.title}\n\n{text}"
    )
