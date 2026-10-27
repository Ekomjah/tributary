from __future__ import annotations

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from tributary.config import Settings
from tributary.observability import init_sentry


def _clear_sentry_env(monkeypatch) -> None:
    for key in (
        "SENTRY_DSN",
        "TRIBUTARY_SENTRY_DSN",
        "SENTRY_ENABLED",
        "TRIBUTARY_SENTRY_ENABLED",
        "SENTRY_ENVIRONMENT",
        "TRIBUTARY_SENTRY_ENVIRONMENT",
        "SENTRY_TRACES_SAMPLE_RATE",
        "TRIBUTARY_SENTRY_TRACES_SAMPLE_RATE",
        "SENTRY_PROFILES_SAMPLE_RATE",
        "TRIBUTARY_SENTRY_PROFILES_SAMPLE_RATE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_sentry_is_enabled_by_default_when_a_dsn_exists(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")

    init_sentry(Settings(_env_file=None))

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["dsn"] == "https://public@example.com/1"
    assert kwargs["release"].startswith("tributary@")
    assert kwargs["environment"] == "development"
    assert kwargs["data_collection"] == {
        "user_info": False,
        "cookies": {"mode": "off"},
        "http_headers": {"request": {"mode": "off"}},
        "http_bodies": [],
        "url_query_params": {"mode": "off"},
        "graphql": {"document": False, "variables": False},
        "gen_ai": {"inputs": False, "outputs": False},
        "database_query_data": False,
        "queues": False,
        "stack_frame_variables": False,
        "frame_context_lines": 0,
    }
    assert kwargs["max_request_body_size"] == "never"
    assert kwargs["traces_sample_rate"] == 0.25
    assert kwargs["profile_session_sample_rate"] == 0.1
    assert kwargs["profile_lifecycle"] == "trace"
    assert kwargs["enable_logs"] is True

    integrations = kwargs["integrations"]
    assert any(isinstance(item, FastApiIntegration) for item in integrations)
    assert any(isinstance(item, SqlalchemyIntegration) for item in integrations)
    assert any(isinstance(item, HttpxIntegration) for item in integrations)


def test_sentry_can_be_opted_out(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("SENTRY_ENABLED", "false")

    init_sentry(Settings(_env_file=None))

    assert calls == []


def test_sentry_stays_inactive_without_a_dsn(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)

    init_sentry(Settings(_env_file=None))

    assert calls == []


def test_sentry_sampling_can_be_tuned(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")
    monkeypatch.setenv("SENTRY_PROFILES_SAMPLE_RATE", "0.5")

    init_sentry(Settings(_env_file=None))

    assert calls[0]["environment"] == "production"
    assert calls[0]["traces_sample_rate"] == 1.0
    assert calls[0]["profile_session_sample_rate"] == 0.5
