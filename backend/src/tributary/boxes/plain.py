from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from ..models import Item
from ..schemas import ItemOut
from ..services import articles, feeds
from .base import BoxError, RunContext

logger = logging.getLogger(__name__)

__all__ = [
    "DedupeBox",
    "FetchBox",
    "FilterBox",
    "FullTextBox",
    "LimitBox",
    "MergeBox",
    "SortBox",
]


class FetchBox:
    """Fetch one or more RSS feeds and return their stored items."""

    box = "fetch"

    def __init__(self, urls: list[str]) -> None:
        self.urls = urls

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        collected: list[ItemOut] = []
        errors: list[str] = []

        for url in self.urls:
            result = feeds.fetch_feed(
                context.session,
                url,
                client=context.client,
                min_full_chars=context.settings.article_min_chars,
            )
            if result.error:
                errors.append(f"{result.url}: {result.error}")
                continue
            if result.feed_id is None:
                continue

            context.session.flush()
            stored = context.session.scalars(
                select(Item)
                .where(Item.feed_id == result.feed_id)
                .order_by(
                    Item.published.is_(None),
                    Item.published.desc(),
                    Item.fetched_at.desc(),
                    Item.id.desc(),
                )
            ).all()
            collected.extend(ItemOut.model_validate(item) for item in stored)

        if errors and not collected:
            raise BoxError("fetch failed for every URL: " + "; ".join(errors))
        if errors:
            logger.warning("Some pipe feeds failed: %s", "; ".join(errors))

        context.sources.append(collected)
        return collected


class MergeBox:
    """Join the outputs of the Fetch boxes since the last Merge."""

    box = "merge"

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        if not context.sources:
            return items

        merged = [item for source in context.sources for item in source]
        context.sources = [merged]
        return merged


class DedupeBox:
    """Drop repeated items, keeping the first occurrence."""

    box = "dedupe"

    def __init__(self, by: str = "link") -> None:
        self.by = by

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        seen: set[str] = set()
        unique: list[ItemOut] = []

        for item in items:
            key = self._key(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique

    def _key(self, item: ItemOut) -> str:
        if self.by == "guid":
            return item.guid
        if self.by == "title":
            return item.title.strip().casefold() or item.guid
        if item.link:
            return feeds.normalize_url(item.link)
        return item.guid


class FilterBox:
    """Keep items whose chosen fields contain a keyword."""

    box = "filter"

    def __init__(self, keyword: str, fields: list[str] | None = None) -> None:
        self.keyword = keyword.casefold()
        self.fields = fields or ["title", "content"]

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        kept: list[ItemOut] = []
        for item in items:
            values = [self._field(item, field) for field in self.fields]
            if any(self.keyword in value.casefold() for value in values if value):
                kept.append(item)
        return kept

    @staticmethod
    def _field(item: ItemOut, field: str) -> str:
        value: Any = getattr(item, field, "")
        return "" if value is None else str(value)


class SortBox:
    """Sort items by date or title, with missing values last."""

    box = "sort"

    def __init__(self, by: str = "published", order: str = "desc") -> None:
        self.by = by
        self.order = order

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        present = [item for item in items if getattr(item, self.by) is not None]
        missing = [item for item in items if getattr(item, self.by) is None]
        present.sort(
            key=self._value,
            reverse=self.order == "desc",
        )
        return present + missing

    def _value(self, item: ItemOut) -> Any:
        value = getattr(item, self.by)
        if self.by == "title":
            return str(value).casefold()
        return value


class LimitBox:
    """Keep at most ``count`` items from the front of the stream."""

    box = "limit"

    def __init__(self, count: int = 10) -> None:
        self.count = count

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        return items[: self.count]


class FullTextBox:
    """Replace each item's text with the best full text available.

    Long feed content is used as-is; otherwise the article page is fetched
    once and cached on the item, exactly like opening it in the reader.
    """

    box = "fulltext"

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        enriched: list[ItemOut] = []

        for item in items:
            row = context.session.get(Item, item.id)
            if row is None:
                enriched.append(item)
                continue

            articles.fetch_article(
                context.session,
                row,
                settings=context.settings,
                client=context.client,
            )
            context.session.flush()
            enriched.append(ItemOut.model_validate(row))

        return enriched
