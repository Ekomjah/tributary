from __future__ import annotations

import pytest

from tributary.services import urls


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/feed",
        "http://localhost/feed",
        "http://printer.local/feed",
        "http://wiki.internal/feed",
        "http://[::1]/feed",
        "http://10.0.0.1/feed",
        "http://192.168.1.1/feed",
        "http://172.16.0.1/feed",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/feed",
        "http://100.64.0.1/feed",
        "http://[fc00::1]/feed",
    ],
)
def test_validate_public_url_rejects_private_hosts(url: str) -> None:
    with pytest.raises(urls.UnsafeUrlError):
        urls.validate_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pass@example.com/feed",
        "https://user@example.com/feed",
    ],
)
def test_validate_public_url_rejects_credentials(url: str) -> None:
    with pytest.raises(urls.UnsafeUrlError):
        urls.validate_public_url(url)


def test_validate_public_url_rejects_a_hostname_that_resolves_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urls, "_resolve_host", lambda host, port: ["127.0.0.1"])

    with pytest.raises(urls.UnsafeUrlError):
        urls.validate_public_url("https://evil.example/feed")


def test_validate_public_url_rejects_a_mixed_public_and_private_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urls,
        "_resolve_host",
        lambda host, port: ["93.184.216.34", "127.0.0.1"],
    )

    with pytest.raises(urls.UnsafeUrlError):
        urls.validate_public_url("https://evil.example/feed")


def test_validate_public_url_allows_a_public_host() -> None:
    assert urls.validate_public_url("https://example.com/feed") == "https://example.com/feed"


def test_normalize_input_url_adds_https() -> None:
    assert urls.normalize_input_url("example.com/feed") == "https://example.com/feed"


def test_redact_url_drops_credentials_and_query() -> None:
    assert (
        urls.redact_url("https://user:pass@example.com/feed?token=secret#fragment")
        == "https://example.com/feed"
    )


def test_redact_urls_in_text_handles_embedded_urls() -> None:
    text = "failed for url 'https://user:pass@example.com/feed?token=secret'"

    assert urls.redact_urls_in_text(text) == "failed for url 'https://example.com/feed'"
