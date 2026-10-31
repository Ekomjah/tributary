from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

LOCAL_TEMPLATE = REPO_ROOT / ".env.local.example"
CLOUD_TEMPLATE = REPO_ROOT / ".env.cloud.example"
REFERENCE = REPO_ROOT / ".env.example"

LOCAL_REQUIRED = {
    "DEV_ENV",
    "TRIBUTARY_DB_PATH",
    "OLLAMA_CLOUD",
    "OLLAMA_MODEL",
    "OLLAMA_HOST",
    "SERPAPI_API_KEY",
    "SENTRY_DSN",
}

CLOUD_REQUIRED = {
    "DEV_ENV",
    "DATABASE",
    "DATABASE_URL",
    "DATABASE_URL_UNPOOLED",
    "AUTH0_DOMAIN",
    "AUTH0_AUDIENCE",
    "AUTH0_CLIENT_ID",
    "CORS_ORIGINS",
    "OLLAMA_CLOUD",
    "OLLAMA_API_KEY",
    "OLLAMA_CLOUD_MODEL",
    "OLLAMA_CLOUD_HOST",
}


def _assignments(path: Path) -> dict[str, str]:
    """Return active ``KEY=value`` pairs from a dotenv-style template."""

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_local_template_documents_required_keys() -> None:
    values = _assignments(LOCAL_TEMPLATE)
    assert LOCAL_REQUIRED <= values.keys()
    assert values["DEV_ENV"] == ""
    assert values["OLLAMA_CLOUD"] == "false"


def test_cloud_template_documents_required_keys() -> None:
    values = _assignments(CLOUD_TEMPLATE)
    assert CLOUD_REQUIRED <= values.keys()
    assert values["DEV_ENV"]
    assert values["OLLAMA_CLOUD"] == "true"


def test_templates_only_use_documented_keys() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")
    for template in (LOCAL_TEMPLATE, CLOUD_TEMPLATE):
        for key in _assignments(template):
            assert key in reference, f"{key} is missing from .env.example"
