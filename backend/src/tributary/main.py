from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api import feeds, items, labels, pipes, refine, runs, search_source
from .config import Settings, get_settings
from .db import create_engine, create_session_factory, init_db
from .observability import init_sentry
from .schemas import HealthOut
from .services import pipe_runs

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    init_sentry(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(resolved_settings)
        init_db(engine, resolved_settings)
        app.state.settings = resolved_settings
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        reaped = pipe_runs.reap_interrupted_runs(app.state.session_factory)
        if reaped:
            logger.warning("Marked %d interrupted pipe run(s) as failed", reaped)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "name": resolved_settings.app_name,
            "version": resolved_settings.version,
            "docs": "/docs",
        }

    @app.get("/health", response_model=HealthOut, tags=["meta"])
    def health(request: Request) -> HealthOut:
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=503, detail="database unavailable") from exc

        return HealthOut(
            status="ok",
            app=resolved_settings.app_name,
            version=resolved_settings.version,
            database=resolved_settings.database_label,
        )

    for router in (
        feeds.router,
        items.router,
        labels.router,
        pipes.router,
        refine.router,
        runs.router,
        search_source.router,
    ):
        app.include_router(router, prefix="/api")

    return app


app = create_app()
