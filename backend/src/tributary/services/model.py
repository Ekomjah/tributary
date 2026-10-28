from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import ollama

from ..config import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "ModelClient",
    "ModelError",
    "OllamaModelClient",
    "check_ollama",
]


class ModelError(RuntimeError):
    """The local model is unavailable or returned an unusable answer."""


class ModelClient(Protocol):
    """The small slice of a chat model the AI boxes need."""

    model: str

    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
    ) -> dict[str, Any]:
        """Return a JSON object that matches ``schema``."""


@dataclass(slots=True)
class OllamaModelClient:
    """Talk to a local Ollama server with structured output."""

    model: str
    host: str
    timeout: float = 120.0
    _client: ollama.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = ollama.Client(host=self.host, timeout=self.timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> OllamaModelClient:
        return cls(
            model=settings.ollama_model,
            host=settings.ollama_host,
            timeout=settings.ollama_timeout,
        )

    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._client.chat(
                model=self.model,
                messages=messages,
                format=schema,
                options={"temperature": 0},
            )
        except Exception as exc:
            logger.warning("Ollama call failed: %s", type(exc).__name__)
            raise ModelError(
                f"Could not reach Ollama at {self.host}. Is it running?"
            ) from exc

        content = response.message.content or ""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Ollama returned invalid JSON")
            raise ModelError("The model did not return valid JSON.") from exc

        if not isinstance(data, dict):
            raise ModelError("The model did not return a JSON object.")
        return data


def check_ollama(settings: Settings) -> tuple[bool, str, list[str]]:
    """Return (reachable, detail, installed model names) for ``doctor``."""

    try:
        client = ollama.Client(
            host=settings.ollama_host,
            timeout=min(settings.ollama_timeout, 5.0),
        )
        response = client.list()
    except Exception as exc:
        return False, f"cannot reach {settings.ollama_host} ({type(exc).__name__})", []

    names = sorted(
        {
            str(getattr(entry, "model", "") or getattr(entry, "name", "") or "")
            for entry in getattr(response, "models", [])
        }
        - {""}
    )
    return True, f"reachable at {settings.ollama_host}", names
