# syntax=docker/dockerfile:1

# Tributary API. The application is a single FastAPI process that owns one
# SQLite file (or PostgreSQL, when DATABASE_URL is set), so there is no
# database service and no separate migration container: `tributary serve`
# applies migrations on startup.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# `.python-version` pins 3.10 for local development; the image builds on the
# 3.12 interpreter that ships with the base image. UV_PYTHON overrides the
# version file, and downloads stay off so the build never fetches a runtime.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=3.12 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app/backend

# Resolve dependencies before the source lands so edits do not bust the cache.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Tributary API" \
      org.opencontainers.image.description="Self-hosted feed reader and pipe builder API" \
      org.opencontainers.image.source="https://github.com/Ekomjah/tributary"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/backend/.venv/bin:$PATH" \
    TRIBUTARY_HOST=0.0.0.0 \
    TRIBUTARY_PORT=8000 \
    TRIBUTARY_DB_PATH=/data/tributary/tributary.db

# The database lives in a child of the volume mount point: a volume mounted at
# /data replaces that directory's ownership, but a directory the image created
# inside it keeps the ownership set here.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/tributary \
    && chown -R app:app /data

WORKDIR /app/backend
COPY --from=builder --chown=app:app /app/backend /app/backend

USER app

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]

CMD ["tributary", "serve"]
