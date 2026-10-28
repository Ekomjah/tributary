from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

__all__ = [
    "UnsafeUrlError",
    "normalize_input_url",
    "redact_url",
    "redact_urls_in_text",
    "validate_public_url",
]

_ALLOWED_SCHEMES = {"http", "https"}
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}"


class UnsafeUrlError(ValueError):
    """A URL that Tributary refuses to request."""


def _resolve_host(host: str, port: int) -> list[str]:
    """Resolve a hostname to every address the process might connect to."""

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError("url host could not be resolved") from exc

    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    return addresses


def _require_public_address(address: str) -> None:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeUrlError("url host is not a public address") from exc
    if not ip.is_global:
        raise UnsafeUrlError("url host is not a public address")


def _split(url: str) -> tuple[str, str, str, str, str]:
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise UnsafeUrlError("url could not be parsed") from exc

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("url must be an absolute http(s) URL")
    if not parts.hostname:
        raise UnsafeUrlError("url must include a host")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("url must not contain credentials")
    return scheme, parts.netloc, parts.path, parts.query, parts.hostname


def normalize_input_url(value: str) -> str:
    """Turn a user-entered address into a canonical absolute URL."""

    cleaned = value.strip()
    if not cleaned:
        raise UnsafeUrlError("url is empty")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    scheme, netloc, path, query, _hostname = _split(cleaned)
    return urlunsplit((scheme, netloc.lower(), path or "/", query, ""))


def validate_public_url(url: str) -> str:
    """Reject URLs that could reach the local machine or a private network.

    Every hostname is resolved and *all* answers must be globally routable, so a
    DNS name that mixes a public and a private address is rejected as well.
    """

    scheme, _netloc, _path, _query, hostname = _split(url)
    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrlError("url host is not public")

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        port = 443 if scheme == "https" else 80
        try:
            parsed = urlsplit(url.strip())
            port = parsed.port or port
        except ValueError as exc:
            raise UnsafeUrlError("url port is invalid") from exc

        addresses = _resolve_host(host, port)
        if not addresses:
            raise UnsafeUrlError("url host could not be resolved") from None
        for address in addresses:
            _require_public_address(address)
    else:
        _require_public_address(host)

    return url


def redact_url(url: str) -> str:
    """Drop credentials, the query string, and the fragment from a URL."""

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "[redacted]"

    if not parts.scheme or not parts.hostname:
        return url.split("?", 1)[0].split("#", 1)[0]

    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port:
        host = f"{host}:{port}"

    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def redact_urls_in_text(text: str) -> str:
    """Redact every URL embedded in a log line or an error message."""

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in _TRAILING_PUNCTUATION:
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        return redact_url(raw) + trailing

    return _URL_PATTERN.sub(replace, text)
