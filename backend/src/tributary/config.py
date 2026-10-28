from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_DIR.parents[1]
REPO_ROOT = PACKAGE_DIR.parents[2]


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ROOT / ".env"), str(REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Tributary"
    version: str = "0.1.0"

    db_path: Path = Field(
        default=REPO_ROOT / "tributary.db",
        validation_alias=AliasChoices("TRIBUTARY_DB_PATH", "DB_PATH"),
    )
    ollama_model: str = Field(
        default="gemma3:1b",
        validation_alias=AliasChoices("OLLAMA_MODEL", "TRIBUTARY_OLLAMA_MODEL"),
    )
    ollama_host: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_HOST", "TRIBUTARY_OLLAMA_HOST"),
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

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
