from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from . import __version__
from .config import Settings
from .services.urls import redact_urls_in_text

logger = logging.getLogger(__name__)

_API_KEY = re.compile(r"(api[_-]?key=)[^&\s\"']+", re.IGNORECASE)


def _scrub(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """Redact API keys and known secret values from Sentry payloads."""

    if isinstance(value, str):
        cleaned = _API_KEY.sub(r"\1[Filtered]", value)
        for secret in secrets:
            cleaned = cleaned.replace(secret, "[Filtered]")
        return redact_urls_in_text(cleaned)
    if isinstance(value, dict):
        return {key: _scrub(entry, secrets) for key, entry in value.items()}
    if isinstance(value, list):
        return [_scrub(entry, secrets) for entry in value]
    if isinstance(value, tuple):
        return tuple(_scrub(entry, secrets) for entry in value)
    return value


def _make_scrubber(secrets: Iterable[str] = ()):
    """Build a callback that fits before_send, before_send_transaction and logs."""

    known = tuple(secret for secret in secrets if secret and len(secret) >= 8)

    def scrub(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
        return _scrub(event, known)

    return scrub


def init_sentry(settings: Settings) -> None:
    """Enable Sentry only when a DSN is configured.

    Without SENTRY_DSN the SDK is never initialized, so every span, metric,
    exception and log call is a local no-op. The app runs normally without
    tracing or telemetry. When a DSN is present, errors, traces, profiles,
    logs, custom metrics and GenAI spans are enabled; tracing follows
    SENTRY_TRACES_SAMPLE_RATE, so an explicit 0 keeps error reporting on while
    turning tracing off.

    Data collection defaults to what is useful for monitoring this app:
    request bodies, headers and query strings are captured (with the SDK's
    sensitive-key denylist), database query data and stack variables are on,
    and GenAI inputs/outputs are on. Cookies, GraphQL and queues stay off
    because Tributary does not use them. Every switch is exposed through
    Settings so a deployment can tighten it.
    """
    if not settings.sentry_enabled:
        logger.info("Sentry disabled with SENTRY_ENABLED=false")
        return

    if not settings.sentry_dsn:
        logger.info(
            "Sentry inactive: SENTRY_DSN is not set; tracing and error reporting are off"
        )
        return

    scrub = _make_scrubber(
        [settings.serpapi_api_key or "", settings.ollama_api_key or ""]
    )

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        release=f"tributary@{__version__}",
        environment=settings.sentry_environment,
        data_collection={
            "user_info": settings.sentry_send_user_info,
            "cookies": {"mode": "off"},
            "http_headers": {
                "request": (
                    {"mode": "denylist"}
                    if settings.sentry_collect_http_headers
                    else {"mode": "off"}
                )
            },
            "http_bodies": (
                ["incoming_request", "outgoing_request", "outgoing_response"]
                if settings.sentry_collect_http_bodies
                else []
            ),
            "url_query_params": (
                {"mode": "denylist"}
                if settings.sentry_collect_query_params
                else {"mode": "off"}
            ),
            "graphql": {"document": False, "variables": False},
            "gen_ai": {
                "inputs": settings.sentry_collect_gen_ai,
                "outputs": settings.sentry_collect_gen_ai,
            },
            "database_query_data": settings.sentry_collect_db_queries,
            "queues": False,
            "stack_frame_variables": settings.sentry_collect_stack_variables,
            "frame_context_lines": settings.sentry_frame_context_lines,
        },
        max_request_body_size=settings.sentry_max_request_body_size,
        before_send=scrub,
        before_send_transaction=scrub,
        before_send_log=scrub,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profile_session_sample_rate=settings.sentry_profiles_sample_rate,
        profile_lifecycle="trace",
        enable_logs=True,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            HttpxIntegration(),
        ],
    )
    logger.info(
        "Sentry enabled (environment=%s, traces=%s, profiles=%s, gen_ai=%s)",
        settings.sentry_environment,
        settings.sentry_traces_sample_rate,
        settings.sentry_profiles_sample_rate,
        settings.sentry_collect_gen_ai,
    )
