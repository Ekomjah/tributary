from __future__ import annotations

import logging

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from . import __version__
from .config import Settings

logger = logging.getLogger(__name__)


def init_sentry(settings: Settings) -> None:
    """Enable Sentry unless the user opts out.

    Sentry only transmits when a DSN is configured. Keeping the switch on by
    default means deployments that provide a DSN get errors, traces, profiles,
    logs, and custom metrics without extra setup.
    """
    if not settings.sentry_enabled:
        logger.info("Sentry disabled with SENTRY_ENABLED=false")
        return

    if not settings.sentry_dsn:
        logger.info("Sentry is enabled but SENTRY_DSN is not set; telemetry is inactive")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        release=f"tributary@{__version__}",
        environment=settings.sentry_environment,
        send_default_pii=False,
        include_local_variables=False,
        include_source_context=False,
        max_request_body_size="never",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        enable_logs=True,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            HttpxIntegration(),
        ],
    )
    logger.info(
        "Sentry enabled (environment=%s, traces=%s, profiles=%s)",
        settings.sentry_environment,
        settings.sentry_traces_sample_rate,
        settings.sentry_profiles_sample_rate,
    )
