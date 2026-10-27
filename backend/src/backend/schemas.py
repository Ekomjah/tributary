from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Decision = Literal["keep", "drop"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LabelOut(ORMModel):
    id: int
    name: str


class FeedCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=500)


class FeedOut(ORMModel):
    id: int
    url: str
    title: str
    last_fetched: datetime | None = None
    last_error: str | None = None
    created_at: datetime


class ItemOut(ORMModel):
    id: int
    feed_id: int
    guid: str
    title: str
    link: str | None = None
    published: datetime | None = None
    content: str
    is_read: bool
    starred: bool
    decision: Decision | None = None
    fetched_at: datetime
    labels: list[LabelOut] = Field(default_factory=list)
    summary: str | None = None


class ItemUpdate(BaseModel):
    is_read: bool | None = None
    starred: bool | None = None
    decision: Decision | None = None


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PipeCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    spec_json: dict[str, Any] = Field(default_factory=dict)


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
