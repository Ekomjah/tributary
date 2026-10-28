from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import BoxCache

__all__ = [
    "content_hash",
    "get_cached",
    "params_hash",
    "set_cached",
]


def params_hash(**values: Any) -> str:
    """Hash the inputs that should invalidate a box's cached answer."""

    payload = json.dumps(values, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_cached(
    session: Session,
    *,
    item_id: int,
    box: str,
    params_hash: str,
    model: str,
) -> Any | None:
    row = session.get(BoxCache, (item_id, box, params_hash, model))
    return None if row is None else row.output


def set_cached(
    session: Session,
    *,
    item_id: int,
    box: str,
    params_hash: str,
    model: str,
    output: Any,
) -> None:
    row = session.get(BoxCache, (item_id, box, params_hash, model))
    if row is None:
        session.add(
            BoxCache(
                item_id=item_id,
                box=box,
                params_hash=params_hash,
                model=model,
                output=output,
            )
        )
    else:
        row.output = output
