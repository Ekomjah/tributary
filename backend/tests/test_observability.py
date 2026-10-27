from __future__ import annotations

import sentry_sdk

from tributary.config import Settings
from tributary.observability import init_sentry


def test_sentry_is_skipped_without_a_dsn(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("TRIBUTARY_SENTRY_DSN", raising=False)

    init_sentry(Settings(_env_file=None))

    assert calls == []


def test_sentry_is_enabled_with_a_dsn(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")

    init_sentry(Settings(_env_file=None))

    assert calls == [
        {
            "dsn": "https://public@example.com/1",
            "send_default_pii": False,
            "traces_sample_rate": 0.0,
        }
    ]
