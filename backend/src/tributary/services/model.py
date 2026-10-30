from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, NoReturn, Protocol

import httpx
import ollama
import sentry_sdk
from sentry_sdk.ai.utils import get_start_span_function, set_data_normalized
from sentry_sdk.consts import SPANDATA

from ..config import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "ModelClient",
    "ModelError",
    "OllamaModelClient",
    "check_ollama",
]

_REPEAT_LIMIT = "token repeat limit"
_MAX_OUTPUT_TOKENS = 512


class ModelError(RuntimeError):
    """The model was unreachable, timed out, or rejected the request."""


def _is_repeat_abort(exc: ollama.ResponseError) -> bool:
    """Return whether Ollama stopped a generation that was repeating itself."""

    return _REPEAT_LIMIT in str(getattr(exc, "error", "") or "").lower()


def _describe_failure(
    exc: Exception,
    *,
    host: str,
    timeout: float,
    cloud: bool = False,
) -> str:
    """Name the real failure instead of always blaming availability."""

    service = "Ollama Cloud" if cloud else "Ollama"
    if isinstance(exc, ollama.ResponseError):
        detail = str(getattr(exc, "error", "") or "").strip()
        status = getattr(exc, "status_code", "?")
        message = f"{service} at {host} rejected the request ({status})"
        return f"{message}: {detail}" if detail else f"{message}."
    if isinstance(exc, (ConnectionError, httpx.ConnectError, httpx.ConnectTimeout)):
        if cloud:
            return (
                f"Could not reach {service} at {host}; "
                "check OLLAMA_API_KEY and network access."
            )
        return f"Could not reach Ollama at {host}. Is it running?"
    if isinstance(exc, httpx.TimeoutException):
        return f"{service} at {host} did not finish within {timeout:g}s."
    return f"{service} call failed: {type(exc).__name__}: {exc}"


def _collect_gen_ai(kind: str) -> bool:
    """Return whether Sentry may record model inputs or outputs."""

    client = sentry_sdk.get_client()
    collection = client.options.get("data_collection")
    if collection is not None:
        return bool(collection.get("gen_ai", {}).get(kind, False))
    return client.should_send_default_pii()


def _record_usage(span: Any, response: Any) -> None:
    """Copy Ollama token counts onto a Sentry GenAI span when present."""

    prompt_tokens = getattr(response, "prompt_eval_count", None)
    completion_tokens = getattr(response, "eval_count", None)

    if isinstance(prompt_tokens, int):
        span.set_data(SPANDATA.GEN_AI_USAGE_INPUT_TOKENS, prompt_tokens)
    if isinstance(completion_tokens, int):
        span.set_data(SPANDATA.GEN_AI_USAGE_OUTPUT_TOKENS, completion_tokens)
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        span.set_data(
            SPANDATA.GEN_AI_USAGE_TOTAL_TOKENS,
            prompt_tokens + completion_tokens,
        )


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
    """Talk to a local or cloud Ollama server with structured output."""

    model: str
    host: str
    timeout: float = 120.0
    api_key: str | None = field(default=None, repr=False)
    cloud: bool = False
    _client: ollama.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.api_key
            else {}
        )
        self._client = ollama.Client(
            host=self.host,
            timeout=self.timeout,
            headers=headers,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> OllamaModelClient:
        return cls(
            model=settings.active_ollama_model,
            host=settings.active_ollama_host,
            timeout=settings.ollama_timeout,
            api_key=settings.ollama_api_key if settings.ollama_cloud else None,
            cloud=settings.ollama_cloud,
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

        start_span = get_start_span_function()
        with start_span(op="gen_ai.chat", name=f"chat {self.model}") as span:
            span.set_data(SPANDATA.GEN_AI_OPERATION_NAME, "chat")
            span.set_data(SPANDATA.GEN_AI_PROVIDER_NAME, "ollama")
            # Older Sentry views still read gen_ai.system; keep both in sync.
            span.set_data(SPANDATA.GEN_AI_SYSTEM, "ollama")
            span.set_data(SPANDATA.GEN_AI_REQUEST_MODEL, self.model)
            if _collect_gen_ai("inputs"):
                set_data_normalized(
                    span,
                    SPANDATA.GEN_AI_INPUT_MESSAGES,
                    messages,
                    unpack=False,
                )

            options: dict[str, Any] = {
                "temperature": 0,
                "repeat_penalty": 1.1,
                "repeat_last_n": 128,
                # Every prompt here asks for one sentence, a verdict, or a search
                # query. A cap stops a looping model from generating for minutes.
                "num_predict": _MAX_OUTPUT_TOKENS,
            }

            def fail(exc: Exception) -> NoReturn:
                span.set_status("internal_error")
                message = _describe_failure(
                    exc,
                    host=self.host,
                    timeout=self.timeout,
                    cloud=self.cloud,
                )
                logger.warning("Ollama call failed: %s", message)
                raise ModelError(message) from exc

            for attempt in range(2):
                span.set_data(
                    SPANDATA.GEN_AI_REQUEST_TEMPERATURE,
                    float(options["temperature"]),
                )
                try:
                    response = self._client.chat(
                        model=self.model,
                        messages=messages,
                        format=schema,
                        options=options,
                    )
                    break
                except ollama.ResponseError as exc:
                    if attempt == 0 and _is_repeat_abort(exc):
                        logger.warning(
                            "Ollama aborted a repeating generation; retrying once "
                            "with a higher temperature (%s)",
                            getattr(exc, "error", ""),
                        )
                        options = {**options, "temperature": 0.2}
                        continue
                    fail(exc)
                except Exception as exc:
                    fail(exc)

            content = response.message.content or ""
            span.set_data(
                SPANDATA.GEN_AI_RESPONSE_MODEL,
                getattr(response, "model", None) or self.model,
            )
            _record_usage(span, response)
            if _collect_gen_ai("outputs"):
                set_data_normalized(
                    span,
                    SPANDATA.GEN_AI_OUTPUT_MESSAGES,
                    [{"role": "assistant", "content": content}],
                    unpack=False,
                )

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Ollama returned invalid JSON")
            raise ModelError("The model did not return valid JSON.") from exc

        if not isinstance(data, dict):
            raise ModelError("The model did not return a JSON object.")
        return data


def check_ollama(settings: Settings) -> tuple[bool, str, list[str]]:
    """Return (reachable, detail, available model names) for ``doctor``."""

    if settings.ollama_cloud and not settings.ollama_api_key:
        return False, "OLLAMA_CLOUD=true requires OLLAMA_API_KEY", []

    host = settings.active_ollama_host
    try:
        client = ollama.Client(
            host=host,
            timeout=min(settings.ollama_timeout, 5.0),
            headers=settings.ollama_auth_headers,
        )
        response = client.list()
    except Exception as exc:
        target = f"Ollama Cloud at {host}" if settings.ollama_cloud else host
        return False, f"cannot reach {target} ({type(exc).__name__})", []

    names = sorted(
        {
            str(getattr(entry, "model", "") or getattr(entry, "name", "") or "")
            for entry in getattr(response, "models", [])
        }
        - {""}
    )
    return True, f"reachable at {host}", names
