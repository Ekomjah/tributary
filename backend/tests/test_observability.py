from __future__ import annotations

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from tributary.config import Settings
from tributary.observability import init_sentry

_ENV_KEYS = (
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
    "SENTRY_SEND_USER_INFO",
    "TRIBUTARY_SENTRY_SEND_USER_INFO",
    "SENTRY_COLLECT_HTTP_HEADERS",
    "TRIBUTARY_SENTRY_COLLECT_HTTP_HEADERS",
    "SENTRY_COLLECT_HTTP_BODIES",
    "TRIBUTARY_SENTRY_COLLECT_HTTP_BODIES",
    "SENTRY_COLLECT_QUERY_PARAMS",
    "TRIBUTARY_SENTRY_COLLECT_QUERY_PARAMS",
    "SENTRY_COLLECT_GEN_AI",
    "TRIBUTARY_SENTRY_COLLECT_GEN_AI",
    "SENTRY_COLLECT_DB_QUERIES",
    "TRIBUTARY_SENTRY_COLLECT_DB_QUERIES",
    "SENTRY_COLLECT_STACK_VARIABLES",
    "TRIBUTARY_SENTRY_COLLECT_STACK_VARIABLES",
    "SENTRY_FRAME_CONTEXT_LINES",
    "TRIBUTARY_SENTRY_FRAME_CONTEXT_LINES",
    "SENTRY_MAX_REQUEST_BODY_SIZE",
    "TRIBUTARY_SENTRY_MAX_REQUEST_BODY_SIZE",
    "SERPAPI_API_KEY",
    "OLLAMA_API_KEY",
    "TRIBUTARY_OLLAMA_API_KEY",
)


def _clear_sentry_env(monkeypatch) -> None:
    for key in _ENV_KEYS:
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
        "user_info": True,
        "cookies": {"mode": "off"},
        "http_headers": {"request": {"mode": "denylist"}},
        "http_bodies": [
            "incoming_request",
            "outgoing_request",
            "outgoing_response",
        ],
        "url_query_params": {"mode": "denylist"},
        "graphql": {"document": False, "variables": False},
        "gen_ai": {"inputs": True, "outputs": True},
        "database_query_data": True,
        "queues": False,
        "stack_frame_variables": True,
        "frame_context_lines": 5,
    }
    assert kwargs["max_request_body_size"] == "medium"
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


def test_sentry_data_collection_can_be_tightened(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("SENTRY_SEND_USER_INFO", "false")
    monkeypatch.setenv("SENTRY_COLLECT_HTTP_HEADERS", "false")
    monkeypatch.setenv("SENTRY_COLLECT_HTTP_BODIES", "false")
    monkeypatch.setenv("SENTRY_COLLECT_QUERY_PARAMS", "false")
    monkeypatch.setenv("SENTRY_COLLECT_GEN_AI", "false")
    monkeypatch.setenv("SENTRY_COLLECT_DB_QUERIES", "false")
    monkeypatch.setenv("SENTRY_COLLECT_STACK_VARIABLES", "false")
    monkeypatch.setenv("SENTRY_FRAME_CONTEXT_LINES", "0")
    monkeypatch.setenv("SENTRY_MAX_REQUEST_BODY_SIZE", "never")

    init_sentry(Settings(_env_file=None))

    kwargs = calls[0]
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


def test_scrubber_accepts_the_hint_and_redacts_secrets(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("SERPAPI_API_KEY", "super-secret-serp-key")

    init_sentry(Settings(_env_file=None))

    scrub = calls[0]["before_send"]
    event = {
        "message": "https://serpapi.com/search?api_key=super-secret-serp-key&q=x",
        "extra": {"key": "super-secret-serp-key"},
        "list": ["super-secret-serp-key"],
    }
    scrubbed = scrub(event, {"exc_info": None})

    assert "super-secret-serp-key" not in str(scrubbed)
    assert scrubbed["message"] == "https://serpapi.com/search"
    assert "api_key" not in scrubbed["message"]
    assert scrubbed["extra"]["key"] == "[Filtered]"
    assert scrubbed["list"] == ["[Filtered]"]

    transaction = calls[0]["before_send_transaction"](
        {"spans": [{"data": {"db": "api_key=super-secret-serp-key"}}]},
        {},
    )
    assert "super-secret-serp-key" not in str(transaction)

    log = calls[0]["before_send_log"](
        {"body": "api_key=super-secret-serp-key", "attributes": {}},
        {},
    )
    assert log["body"] == "api_key=[Filtered]"


def test_scrubber_redacts_the_ollama_api_key(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("OLLAMA_API_KEY", "cloud-secret-key")

    init_sentry(Settings(_env_file=None))

    scrub = calls[0]["before_send"]
    scrubbed = scrub(
        {
            "message": "Authorization: Bearer cloud-secret-key",
            "extra": {"key": "cloud-secret-key"},
        },
        {},
    )

    assert "cloud-secret-key" not in str(scrubbed)
    assert scrubbed["extra"]["key"] == "[Filtered]"


def test_scrubber_strips_url_queries_and_credentials(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")

    init_sentry(Settings(_env_file=None))

    scrub = calls[0]["before_send"]
    event = {
        "request": {"url": "https://user:pass@example.com/feed?token=secret#frag"},
        "message": "GET https://example.com/feed?token=secret failed",
        "breadcrumbs": [{"data": {"url": "https://example.com/a?b=c"}}],
    }
    scrubbed = scrub(event, {})

    assert scrubbed["request"]["url"] == "https://example.com/feed"
    assert scrubbed["message"] == "GET https://example.com/feed failed"
    assert scrubbed["breadcrumbs"][0]["data"]["url"] == "https://example.com/a"
    assert "secret" not in str(scrubbed)
    assert "user:pass" not in str(scrubbed)
