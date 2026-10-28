from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from ..config import Settings
from ..schemas import ItemOut
from ..services.model import ModelClient, OllamaModelClient
from ..services.refine import OllamaSearchRefiner, SearchRefiner


class BoxError(RuntimeError):
    """A box could not complete its work."""


@dataclass(slots=True)
class RunContext:
    """Services and working state shared by the boxes in one pipe run."""

    session: Session
    settings: Settings
    client: httpx.Client
    sources: list[list[ItemOut]] = field(default_factory=list)
    model: ModelClient | None = None
    refiner: SearchRefiner | None = None

    def model_client(self) -> ModelClient:
        if self.model is None:
            self.model = OllamaModelClient.from_settings(self.settings)
        return self.model

    def search_refiner(self) -> SearchRefiner:
        if self.refiner is None:
            self.refiner = OllamaSearchRefiner.from_settings(
                self.settings,
                self.model_client(),
            )
        return self.refiner


class Box(Protocol):
    """A pipe step: take items in, return items out."""

    box: str

    def run(self, items: list[ItemOut], context: RunContext) -> list[ItemOut]:
        """Transform the current item stream."""
