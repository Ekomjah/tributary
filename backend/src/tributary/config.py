from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_DIR.parents[1]
REPO_ROOT = PACKAGE_DIR.parents[2]

class ConfigurationError(RuntimeError):
    """The environment configuration is invalid."""


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ROOT / ".env"), str(REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_name: str = "Tributary"
    version: str = "0.1.0"

    db_path: Path = Field(
        default=REPO_ROOT / "tributary.db",
        validation_alias=AliasChoices("TRIBUTARY_DB_PATH", "DB_PATH"),
    )
    # Optional storage selector. Empty means "infer from DATABASE_URL, else
    # SQLite". Set to ``postgres`` on a hosted deployment so a missing URL fails
    # loudly instead of silently falling back to a throwaway SQLite file.
    database: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE", "TRIBUTARY_DATABASE"),
    )
    # When set, DATABASE_URL wins over TRIBUTARY_DB_PATH. SQLite and PostgreSQL
    # are supported; Render's postgres:// and postgresql:// forms as well as
    # Neon's pooled URLs are normalized to the psycopg SQLAlchemy dialect.
    database_url_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "TRIBUTARY_DATABASE_URL"),
    )
    # Neon recommends running DDL over the direct (non-pooler) host. When set,
    # Alembic and ``init-db`` use this URL while the application keeps using the
    # pooled DATABASE_URL.
    migration_database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MIGRATION_DATABASE_URL",
            "TRIBUTARY_MIGRATION_DATABASE_URL",
        ),
    )
    # PostgreSQL pool tuning. The defaults fit a single small Render instance
    # talking to Neon; each worker owns at most pool_size + max_overflow
    # connections.
    database_pool_size: int = Field(
        default=5,
        ge=1,
        validation_alias=AliasChoices(
            "DATABASE_POOL_SIZE",
            "TRIBUTARY_DATABASE_POOL_SIZE",
        ),
    )
    database_max_overflow: int = Field(
        default=5,
        ge=0,
        validation_alias=AliasChoices(
            "DATABASE_MAX_OVERFLOW",
            "TRIBUTARY_DATABASE_MAX_OVERFLOW",
        ),
    )
    database_pool_timeout: float = Field(
        default=30.0,
        gt=0,
        validation_alias=AliasChoices(
            "DATABASE_POOL_TIMEOUT",
            "TRIBUTARY_DATABASE_POOL_TIMEOUT",
        ),
    )
    database_pool_recycle: int = Field(
        default=300,
        ge=0,
        validation_alias=AliasChoices(
            "DATABASE_POOL_RECYCLE",
            "TRIBUTARY_DATABASE_POOL_RECYCLE",
        ),
    )
    database_connect_timeout: int = Field(
        default=10,
        ge=1,
        validation_alias=AliasChoices(
            "DATABASE_CONNECT_TIMEOUT",
            "TRIBUTARY_DATABASE_CONNECT_TIMEOUT",
        ),
    )
    # Local mode (the default) talks to Ollama on this machine.
    ollama_model: str = Field(
        default="gemma3:1b",
        validation_alias=AliasChoices("OLLAMA_MODEL", "TRIBUTARY_OLLAMA_MODEL"),
    )
    ollama_host: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_HOST", "TRIBUTARY_OLLAMA_HOST"),
    )
    # Cloud mode is opt-in and uses its own host/model so stale local values in
    # .env do not silently keep the app pointed at localhost.
    ollama_cloud: bool = Field(
        default=False,
        validation_alias=AliasChoices("OLLAMA_CLOUD", "TRIBUTARY_OLLAMA_CLOUD"),
    )
    ollama_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("OLLAMA_API_KEY", "TRIBUTARY_OLLAMA_API_KEY"),
    )
    ollama_cloud_model: str = Field(
        default="gemma4:3b",
        validation_alias=AliasChoices(
            "OLLAMA_CLOUD_MODEL",
            "TRIBUTARY_OLLAMA_CLOUD_MODEL",
        ),
    )
    ollama_cloud_host: str = Field(
        default="https://ollama.com",
        validation_alias=AliasChoices(
            "OLLAMA_CLOUD_HOST",
            "TRIBUTARY_OLLAMA_CLOUD_HOST",
        ),
    )
    ollama_timeout: float = Field(
        default=120.0,
        gt=0,
        validation_alias=AliasChoices("OLLAMA_TIMEOUT", "TRIBUTARY_OLLAMA_TIMEOUT"),
    )
    host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("TRIBUTARY_HOST", "HOST"),
    )
    port: int = Field(
        default=8000,
        validation_alias=AliasChoices("TRIBUTARY_PORT", "PORT"),
    )
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("TRIBUTARY_LOG_LEVEL", "LOG_LEVEL"),
    )
    fetch_timeout: float = Field(
        default=20.0,
        gt=0,
        validation_alias=AliasChoices("TRIBUTARY_FETCH_TIMEOUT", "FETCH_TIMEOUT"),
    )
    article_timeout: float = Field(
        default=15.0,
        gt=0,
        validation_alias=AliasChoices("TRIBUTARY_ARTICLE_TIMEOUT", "ARTICLE_TIMEOUT"),
    )
    article_max_bytes: int = Field(
        default=2_000_000,
        gt=0,
        validation_alias=AliasChoices(
            "TRIBUTARY_ARTICLE_MAX_BYTES",
            "ARTICLE_MAX_BYTES",
        ),
    )
    article_delay_seconds: float = Field(
        default=1.0,
        ge=0.0,
        validation_alias=AliasChoices(
            "TRIBUTARY_ARTICLE_DELAY",
            "ARTICLE_DELAY",
        ),
    )
    article_min_chars: int = Field(
        default=500,
        ge=1,
        validation_alias=AliasChoices(
            "TRIBUTARY_ARTICLE_MIN_CHARS",
            "ARTICLE_MIN_CHARS",
        ),
    )
    serpapi_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SERPAPI_API_KEY", "TRIBUTARY_SERPAPI_API_KEY"),
    )
    serpapi_engine: Literal["google_news", "google"] = Field(
        default="google_news",
        validation_alias=AliasChoices("SERPAPI_ENGINE", "TRIBUTARY_SERPAPI_ENGINE"),
    )
    serpapi_max_results: int = Field(
        default=10,
        ge=1,
        le=20,
        validation_alias=AliasChoices(
            "SERPAPI_MAX_RESULTS",
            "TRIBUTARY_SERPAPI_MAX_RESULTS",
        ),
    )
    serpapi_cache_ttl: int = Field(
        default=21_600,
        ge=60,
        validation_alias=AliasChoices(
            "SERPAPI_CACHE_TTL",
            "TRIBUTARY_SERPAPI_CACHE_TTL",
        ),
    )
    serpapi_timeout: float = Field(
        default=20.0,
        gt=0,
        validation_alias=AliasChoices("SERPAPI_TIMEOUT", "TRIBUTARY_SERPAPI_TIMEOUT"),
    )
    user_agent: str = Field(
        default="Tributary/0.1 (+https://github.com/Ekomjah/tributary)",
        validation_alias=AliasChoices("TRIBUTARY_USER_AGENT", "USER_AGENT"),
    )
    sentry_dsn: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SENTRY_DSN", "TRIBUTARY_SENTRY_DSN"),
    )
    sentry_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("SENTRY_ENABLED", "TRIBUTARY_SENTRY_ENABLED"),
    )
    sentry_environment: str = Field(
        default="development",
        validation_alias=AliasChoices("SENTRY_ENVIRONMENT", "TRIBUTARY_SENTRY_ENVIRONMENT"),
    )
    sentry_traces_sample_rate: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "SENTRY_TRACES_SAMPLE_RATE",
            "TRIBUTARY_SENTRY_TRACES_SAMPLE_RATE",
        ),
    )
    sentry_profiles_sample_rate: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "SENTRY_PROFILES_SAMPLE_RATE",
            "TRIBUTARY_SENTRY_PROFILES_SAMPLE_RATE",
        ),
    )
    # Sentry's data_collection defaults are monitoring-oriented. These switches
    # let a deployment tighten or widen what leaves the machine without editing
    # code. Secrets are still redacted by the scrubber in observability.py.
    sentry_send_user_info: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SENTRY_SEND_USER_INFO",
            "TRIBUTARY_SENTRY_SEND_USER_INFO",
        ),
    )
    sentry_collect_http_headers: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SENTRY_COLLECT_HTTP_HEADERS",
            "TRIBUTARY_SENTRY_COLLECT_HTTP_HEADERS",
        ),
    )
    sentry_collect_http_bodies: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SENTRY_COLLECT_HTTP_BODIES",
            "TRIBUTARY_SENTRY_COLLECT_HTTP_BODIES",
        ),
    )
    sentry_collect_query_params: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SENTRY_COLLECT_QUERY_PARAMS",
            "TRIBUTARY_SENTRY_COLLECT_QUERY_PARAMS",
        ),
    )
    sentry_collect_gen_ai: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SENTRY_COLLECT_GEN_AI",
            "TRIBUTARY_SENTRY_COLLECT_GEN_AI",
        ),
    )
    sentry_collect_db_queries: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SENTRY_COLLECT_DB_QUERIES",
            "TRIBUTARY_SENTRY_COLLECT_DB_QUERIES",
        ),
    )
    sentry_collect_stack_variables: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SENTRY_COLLECT_STACK_VARIABLES",
            "TRIBUTARY_SENTRY_COLLECT_STACK_VARIABLES",
        ),
    )
    sentry_frame_context_lines: int = Field(
        default=5,
        ge=0,
        le=50,
        validation_alias=AliasChoices(
            "SENTRY_FRAME_CONTEXT_LINES",
            "TRIBUTARY_SENTRY_FRAME_CONTEXT_LINES",
        ),
    )
    sentry_max_request_body_size: Literal["never", "small", "medium", "always"] = Field(
        default="medium",
        validation_alias=AliasChoices(
            "SENTRY_MAX_REQUEST_BODY_SIZE",
            "TRIBUTARY_SENTRY_MAX_REQUEST_BODY_SIZE",
        ),
    )
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("db_path")
    @classmethod
    def _resolve_db_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            value = REPO_ROOT / value
        return value.expanduser().resolve()

    @field_validator("database", mode="before")
    @classmethod
    def _clean_database_selector(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if text in {"", "auto"}:
            return ""
        if text in {"postgres", "postgresql"}:
            return "postgres"
        if text == "sqlite":
            return "sqlite"
        raise ValueError("DATABASE must be 'sqlite' or 'postgres'")

    @field_validator("database_url_override", mode="before")
    @classmethod
    def _clean_database_url(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("database_url_override")
    @classmethod
    def _validate_database_url(cls, value: str | None) -> str | None:
        if value is not None:
            _normalize_database_url(value)
        return value

    @field_validator("migration_database_url", mode="before")
    @classmethod
    def _clean_migration_database_url(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("migration_database_url")
    @classmethod
    def _validate_migration_database_url(cls, value: str | None) -> str | None:
        if value is not None:
            _normalize_database_url(value)
        return value

    @field_validator("ollama_api_key", mode="before")
    @classmethod
    def _clean_ollama_api_key(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("sentry_dsn", mode="before")
    @classmethod
    def _clean_sentry_dsn(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator(
        "ollama_model",
        "ollama_host",
        "ollama_cloud_model",
        "ollama_cloud_host",
    )
    @classmethod
    def _validate_ollama_endpoint_value(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Ollama model and host values must not be empty")
        return text

    @model_validator(mode="after")
    def _validate_storage_profile(self) -> Settings:
        if self.database == "postgres" and self.database_url_override is None:
            raise ValueError("DATABASE=postgres requires DATABASE_URL to be set")

        if self.database_url_override is not None and self.database:
            backend = make_url(self.database_url).get_backend_name()
            expected = "postgresql" if self.database == "postgres" else "sqlite"
            if backend != expected:
                raise ValueError(
                    f"DATABASE={self.database} conflicts with the "
                    f"DATABASE_URL backend ({backend})"
                )

        if self.migration_database_url is not None:
            backend = make_url(
                _normalize_database_url(self.migration_database_url)
            ).get_backend_name()
            if backend != "postgresql":
                raise ValueError("MIGRATION_DATABASE_URL must be a PostgreSQL URL")
        return self

    @model_validator(mode="after")
    def _validate_ollama_cloud(self) -> Settings:
        if self.ollama_cloud and not self.ollama_api_key:
            raise ValueError("OLLAMA_CLOUD=true requires OLLAMA_API_KEY")
        return self

    @property
    def database_backend(self) -> str:
        """Return the effective SQLAlchemy backend name."""

        if self.database_url_override:
            return make_url(self.database_url).get_backend_name()
        return "postgresql" if self.database == "postgres" else "sqlite"

    @property
    def migration_url(self) -> str:
        """Return the URL used for DDL, preferring the direct Neon host."""

        if self.migration_database_url:
            return _normalize_database_url(self.migration_database_url)
        return self.database_url

    @property
    def active_ollama_model(self) -> str:
        return self.ollama_cloud_model if self.ollama_cloud else self.ollama_model

    @property
    def active_ollama_host(self) -> str:
        return self.ollama_cloud_host if self.ollama_cloud else self.ollama_host

    @property
    def ollama_auth_headers(self) -> dict[str, str]:
        if not self.ollama_cloud or not self.ollama_api_key:
            return {}
        return {"Authorization": f"Bearer {self.ollama_api_key}"}

    @property
    def sentry_active(self) -> bool:
        return self.sentry_enabled and bool(self.sentry_dsn)

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return _normalize_database_url(self.database_url_override)
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def database_label(self) -> str:
        if self.database_url_override is None:
            return str(self.db_path)
        url = make_url(self.database_url)
        if url.get_backend_name() == "sqlite":
            return str(url.database)
        return url.render_as_string(hide_password=True)



def _normalize_database_url(value: str) -> str:
    """Return a SQLAlchemy URL using the psycopg 3 dialect for PostgreSQL."""

    text = value.strip()
    if text.startswith("postgres://"):
        text = "postgresql+psycopg://" + text[len("postgres://") :]
    elif text.startswith("postgresql://"):
        text = "postgresql+psycopg://" + text[len("postgresql://") :]
    elif text.startswith("postgresql+psycopg2://"):
        text = "postgresql+psycopg://" + text[len("postgresql+psycopg2://") :]

    url = make_url(text)
    backend = url.get_backend_name()
    if backend not in {"sqlite", "postgresql"}:
        raise ValueError(
            f"DATABASE_URL must use SQLite or PostgreSQL, not {backend!r}"
        )
    if backend == "postgresql" and url.get_dialect().driver != "psycopg":
        raise ValueError("PostgreSQL DATABASE_URL must use the psycopg driver")
    return text


def _format_validation_error(exc: ValidationError) -> str:
    """Turn pydantic's multi-line error into a single startup message."""

    messages: list[str] = []
    for error in exc.errors():
        message = str(error.get("msg", "")).strip()
        prefix = "Value error, "
        if message.startswith(prefix):
            message = message[len(prefix) :]
        location = ".".join(
            str(part) for part in error.get("loc", ()) if part != "__root__"
        )
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages) or "invalid configuration"


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from exc
