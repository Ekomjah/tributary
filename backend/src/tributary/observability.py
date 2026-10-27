from __future__ import annotations

import logging

import sentry_sdk

from .config import Settings

logger = logging.getLogger(__name__)


def init_sentry(settings: Settings) -> None:
    """Enable Sentry only when a DSN is configured."""
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
    logger.info("Sentry error monitoring enabled")
