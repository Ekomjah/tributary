from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

Decision = Literal["keep", "drop"]
FetchStatus = Literal["ok", "empty", "blocked", "error"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LabelOut(ORMModel):
    id: int
    name: str


class FeedCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=500)

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        cleaned = value.strip()
        parts = urlsplit(cleaned)
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        return cleaned


class FeedOut(ORMModel):
    id: int
    url: str
    title: str
    kind: str = "feed"
    last_fetched: datetime | None = None
    last_error: str | None = None
    created_at: datetime


class FeedRefreshOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    feed_id: int | None = None
    title: str = ""
    new_items: int = 0
    total_entries: int = 0
    not_modified: bool = False
    error: str | None = None


class ItemOut(ORMModel):
    id: int
    feed_id: int
    guid: str
    title: str
    link: str | None = None
    published: datetime | None = None
    content: str
    content_full: str | None = None
    content_fetched_at: datetime | None = None
    fetch_status: FetchStatus | None = None
    source: str | None = None
    is_read: bool
    starred: bool
    decision: Decision | None = None
    fetched_at: datetime
    labels: list[LabelOut] = Field(default_factory=list)
    summary: str | None = None
    why_care: str | None = None


class ArticleFetchOut(BaseModel):
    id: int
    content_full: str | None = None
    content_fetched_at: datetime | None = None
    fetch_status: FetchStatus | None = None


class ItemUpdate(BaseModel):
    is_read: bool | None = None
    starred: bool | None = None
    decision: Decision | None = None
    label_ids: list[int] | None = None


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


SearchEngine = Literal["google_news", "google"]
SearchFreshness = Literal["day", "week", "month", "year"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    engine: SearchEngine | None = None
    gl: str | None = Field(default=None, min_length=2, max_length=5)
    hl: str | None = Field(default=None, min_length=2, max_length=5)
    freshness: SearchFreshness | None = None
    max_results: int | None = Field(default=None, ge=1, le=20)


class SearchOut(BaseModel):
    query: str
    q: str
    engine: str
    freshness: SearchFreshness | None = None
    cached: bool
    seconds: float
    items: list[ItemOut]


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PipeCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    spec_json: dict[str, Any] = Field(default_factory=dict)


class PipeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    spec_json: dict[str, Any] | None = None


class PipeOut(ORMModel):
    id: int
    name: str
    spec_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RunOut(ORMModel):
    id: int
    pipe_id: int
    started: datetime
    seconds: float | None = None
    status: str
    error: str | None = None
    result_count: int


class BoxRunOut(BaseModel):
    box: str
    seconds: float
    items_in: int
    items_out: int


class PipeRunOut(BaseModel):
    run: RunOut
    items: list[ItemOut]
    steps: list[BoxRunOut]


class BoxCacheOut(ORMModel):
    item_id: int
    box: str
    params_hash: str
    model: str
    output: Any = None
    created_at: datetime


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    database: str
