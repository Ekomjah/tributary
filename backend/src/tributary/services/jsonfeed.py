from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from feedparser.util import FeedParserDict

__all__ = ["JsonFeedError", "parse_json_feed"]


class JsonFeedError(ValueError):
    """A response looked like JSON but was not a usable JSON Feed."""


def parse_json_feed(content: bytes) -> FeedParserDict:
    """Adapt a JSON Feed into the small feedparser shape the reader uses."""

    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonFeedError("response is not a JSON feed") from exc

    if not isinstance(data, dict):
        raise JsonFeedError("response is not a JSON feed")

    version = str(data.get("version") or "")
    if not version.startswith("https://jsonfeed.org/version/"):
        raise JsonFeedError("response is not a JSON feed")

    feed = FeedParserDict()
    feed["title"] = str(data.get("title") or "")
    feed["link"] = str(data.get("home_page_url") or data.get("feed_url") or "")
    feed["description"] = str(data.get("description") or "")

    entries: list[FeedParserDict] = []
    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                entries.append(_parse_entry(item))

    parsed = FeedParserDict()
    parsed["version"] = "json11" if version.rstrip("/").endswith("1.1") else "json10"
    parsed["feed"] = feed
    parsed["entries"] = entries
    return parsed


def _parse_entry(item: dict[str, Any]) -> FeedParserDict:
    entry = FeedParserDict()
    entry["id"] = str(item.get("id") or "")
    entry["title"] = str(item.get("title") or "")
    entry["link"] = str(item.get("url") or item.get("external_url") or "")

    summary = item.get("summary")
    content_html = item.get("content_html")
    content_text = item.get("content_text")
    if summary:
        entry["summary"] = str(summary)
    elif content_text:
        entry["summary"] = str(content_text)

    if content_html:
        entry["content"] = [{"value": str(content_html), "type": "text/html"}]
    elif content_text:
        entry["content"] = [{"value": str(content_text), "type": "text/plain"}]

    image = item.get("image") or item.get("banner_image")
    if image:
        entry["image"] = str(image)

    published = item.get("date_published") or item.get("date_modified")
    if published:
        entry["published"] = str(published)
        parsed_date = _parse_date(str(published))
        if parsed_date is not None:
            entry["published_parsed"] = parsed_date

    return entry


def _parse_date(value: str) -> Any:
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.utctimetuple()
