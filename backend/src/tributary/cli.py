from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import sentry_sdk
import typer
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from . import __version__
from .boxes import BoxError, PipeSpecError, RunContext, load_pipe_spec
from .boxes import run_pipe as execute_pipe
from .config import ConfigurationError, Settings, get_settings
from .db import create_engine, create_session_factory, ensure_local_user, init_db, session_scope
from .models import Feed, Item
from .observability import init_sentry
from .services import discovery, feeds, model, refine
from .services import search as web_search

_SENTRY_READY = False

app = typer.Typer(
    name="tributary",
    help="Tributary feed reader and pipe engine.",
    no_args_is_help=True,
    add_completion=False,
)


def _settings_with_db_path(settings: Settings, db_path: Path | None) -> Settings:
    if db_path is None:
        return settings
    return settings.model_copy(
        update={
            "db_path": db_path.expanduser().resolve(),
            "database": "",
            "database_url_override": None,
            "migration_database_url": None,
        }
    )


def _load_settings(db_path: Path | None = None) -> Settings:
    global _SENTRY_READY
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not _SENTRY_READY:
        init_sentry(settings)
        _SENTRY_READY = True
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return _settings_with_db_path(settings, db_path)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tributary {__version__}")
        raise typer.Exit()


def _model_installed(configured: str, installed: list[str]) -> bool:
    return configured in installed or f"{configured}:latest" in installed


def _training_record(item: Item) -> dict[str, object]:
    return {
        "id": item.id,
        "label": item.decision,
        "starred": item.starred,
        "title": item.title,
        "url": item.link,
        "feed": item.feed.title if item.feed is not None else "",
        "published": item.published.isoformat() if item.published else None,
        "labels": [label.name for label in item.labels],
        "text": item.content_full or item.content,
    }


def _print_fetch_result(result: feeds.FetchResult) -> None:
    label = result.title or result.url
    if result.error:
        typer.echo(f"{label}: {result.error}", err=True)
    elif result.not_modified:
        typer.echo(f"{label}: not modified")
    else:
        typer.echo(
            f"{label}: {result.new_items} new item(s), {result.total_entries} entry/entries"
        )


@app.callback()
def callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Run pipes and manage the local Tributary feed database."""


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Host to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to bind.")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Reload on code changes.")] = False,
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Run the Tributary API server."""
    import uvicorn

    settings = _load_settings(db)
    host = host or settings.host
    port = port or settings.port

    if db is not None:
        os.environ["TRIBUTARY_DB_PATH"] = str(settings.db_path)
        for key in (
            "DATABASE",
            "TRIBUTARY_DATABASE",
            "DATABASE_URL",
            "TRIBUTARY_DATABASE_URL",
            "DATABASE_URL_UNPOOLED",
            "MIGRATION_DATABASE_URL",
            "TRIBUTARY_MIGRATION_DATABASE_URL",
        ):
            os.environ.pop(key, None)

    if reload:
        uvicorn.run(
            "tributary.main:app",
            host=host,
            port=port,
            reload=True,
            log_level=settings.log_level.lower(),
        )
    else:
        from .main import create_app

        uvicorn.run(
            create_app(settings),
            host=host,
            port=port,
            log_level=settings.log_level.lower(),
        )


@app.command("init-db")
def init_database(
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Create the database tables."""
    settings = _load_settings(db)
    engine = create_engine(settings)
    try:
        init_db(engine, settings)
    finally:
        engine.dispose()
    typer.echo(f"Initialized database at {settings.database_label}")


@app.command("discover")
def discover(
    url: Annotated[str, typer.Argument(help="Blog or feed URL to inspect.")],
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Find feed candidates at a URL without subscribing."""
    settings = _load_settings()
    try:
        with feeds.make_client(settings) as client:
            found = discovery.discover_feed(client, url)
    except Exception as exc:
        typer.echo(f"Could not discover a feed at {url}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(asdict(found), indent=2))
    elif found.candidates:
        if found.page_title:
            typer.echo(f"Feeds on {found.page_title}:")
        for candidate in found.candidates:
            label = candidate.title or candidate.kind
            typer.echo(f"{label}: {candidate.url} ({candidate.kind})")
    else:
        typer.echo(f"No feed found at {found.input_url}.", err=True)

    if not found.candidates:
        raise typer.Exit(code=1)


@app.command("fetch")
def fetch(
    url: Annotated[str, typer.Argument(help="Blog or feed URL to fetch and subscribe to.")],
    no_discover: Annotated[
        bool,
        typer.Option(
            "--no-discover",
            help="Treat the URL as the feed itself instead of looking for one.",
        ),
    ] = False,
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Fetch one feed and save its new items."""
    settings = _load_settings(db)
    target = url

    if not no_discover:
        try:
            with feeds.make_client(settings) as client:
                found = discovery.discover_feed(client, url)
        except Exception as exc:
            typer.echo(f"Could not discover a feed at {url}: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if not found.candidates:
            typer.echo(
                f"No feed found at {found.input_url}. If you already have the feed URL, "
                "retry with --no-discover.",
                err=True,
            )
            raise typer.Exit(code=1)

        if len(found.candidates) > 1:
            typer.echo(
                f"Found {len(found.candidates)} feeds at {found.input_url}:",
                err=True,
            )
            for candidate in found.candidates:
                label = candidate.title or candidate.kind
                typer.echo(f"  {label}: {candidate.url}", err=True)
            typer.echo(
                "Run `tributary fetch <feed-url> --no-discover` to choose one.",
                err=True,
            )
            raise typer.Exit(code=2)

        target = found.candidates[0].url

    engine = create_engine(settings)
    try:
        init_db(engine, settings)
        factory = create_session_factory(engine)
        with (
            sentry_sdk.start_transaction(name="feed.fetch", op="task"),
            feeds.make_client(settings) as client,
            session_scope(factory) as session,
        ):
            owner = ensure_local_user(session)
            result = feeds.fetch_feed(
                session,
                target,
                owner_id=owner.id,
                client=client,
                min_full_chars=settings.article_min_chars,
            )
    except Exception as exc:
        typer.echo(f"Could not fetch {target}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    _print_fetch_result(result)
    if result.error:
        raise typer.Exit(code=1)


@app.command("refresh")
def refresh(
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Refresh every subscribed feed."""
    settings = _load_settings(db)
    engine = create_engine(settings)
    try:
        init_db(engine, settings)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            owner_id = ensure_local_user(session).id
        results = feeds.refresh_feeds(factory, settings, owner_id=owner_id)
    except Exception as exc:
        typer.echo(f"Could not refresh feeds: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if not results:
        typer.echo("No feeds yet. Add one with `tributary fetch <url>`.")
        return

    for result in results:
        _print_fetch_result(result)

    if any(not result.ok for result in results):
        raise typer.Exit(code=1)


@app.command("search")
def search_web(
    query: Annotated[str, typer.Argument(help="What to search for, in plain language.")],
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
    max_results: Annotated[
        int | None,
        typer.Option("--max-results", "-n", min=1, max=20, help="How many results to keep."),
    ] = None,
    refine_query: Annotated[
        bool,
        typer.Option(
            "--refine/--no-refine",
            help="Rewrite the request into search keywords with the local model.",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the results as JSON."),
    ] = False,
) -> None:
    """Search the web with SerpAPI and save the results as a search feed."""
    settings = _load_settings(db)
    refined = None
    if refine_query:
        try:
            refined = refine.refine_query(settings, query)
        except web_search.SearchError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        params = refined.to_params(settings)
        if max_results is not None:
            params.max_results = min(max_results, 20)
    else:
        params = web_search.make_params(
            settings,
            query,
            max_results=max_results,
        )

    engine = create_engine(settings)
    try:
        init_db(engine, settings)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            owner = ensure_local_user(session)
            outcome = web_search.run_search(
                session,
                settings,
                params,
                owner_id=owner.id,
                raw_query=query,
            )
    except web_search.SearchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Search failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if refined is not None and json_output:
        typer.echo(
            json.dumps(
                {
                    "spec": refined.spec.model_dump(),
                    "fallback": refined.fallback,
                    "model": refined.model,
                    "seconds": round(refined.seconds, 3),
                },
                ensure_ascii=False,
            ),
            err=True,
        )

    if json_output:
        typer.echo(
            json.dumps(
                [item.model_dump(mode="json") for item in outcome.items],
                ensure_ascii=False,
            )
        )
        return

    status = "cached" if outcome.cached else f"{outcome.seconds:.1f}s"
    typer.echo(
        f"Search: {outcome.query!r} -> {outcome.params.q!r} "
        f"({outcome.params.engine}, {len(outcome.items)} result(s), {status})"
    )
    if refined is not None:
        note = (
            " (local model unavailable, using your words)"
            if refined.fallback
            else f" via {refined.model}"
        )
        typer.echo(f"Refined: {outcome.params.q!r}{note}")
    for item in outcome.items:
        source = f" — {item.source}" if item.source else ""
        typer.echo(f"- {item.title}{source}")


@app.command("run")
def run_pipe_file(
    path: Annotated[Path, typer.Argument(help="Path to a pipe JSON file.")],
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the final items as JSON."),
    ] = False,
) -> None:
    """Run a pipe JSON file."""
    settings = _load_settings(db)
    engine = create_engine(settings)
    try:
        init_db(engine, settings)
        factory = create_session_factory(engine)
        with (
            sentry_sdk.start_transaction(name="pipe.run", op="task") as transaction,
            feeds.make_client(settings) as client,
            session_scope(factory) as session,
        ):
            owner = ensure_local_user(session)
            spec = load_pipe_spec(path)
            transaction.set_data("pipe.name", spec.name or path.stem)
            result = execute_pipe(
                spec,
                RunContext(
                    session=session,
                    settings=settings,
                    client=client,
                    owner_id=owner.id,
                ),
            )
    except (PipeSpecError, BoxError) as exc:
        typer.echo(f"Pipe failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Pipe failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if json_output:
        payload = [item.model_dump(mode="json") for item in result.items]
        typer.echo(json.dumps(payload, indent=2))
        return

    title = result.name or path.stem
    typer.echo(f"{title}: {len(result.items)} item(s) in {result.seconds:.2f}s")
    for index, item in enumerate(result.items, start=1):
        published = item.published.date().isoformat() if item.published else "no date"
        typer.echo(f"{index:>2}. {item.title} ({published})")
        if item.link:
            typer.echo(f"    {item.link}")


@app.command("export")
def export_training(
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write JSONL here instead of stdout."),
    ] = None,
    include_all: Annotated[
        bool,
        typer.Option("--all", help="Include unlabelled items too."),
    ] = False,
) -> None:
    """Export items as JSONL for fine-tuning."""
    settings = _load_settings(db)
    engine = create_engine(settings)
    try:
        init_db(engine, settings)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            owner = ensure_local_user(session)
            stmt = (
                select(Item)
                .join(Item.feed)
                .options(selectinload(Item.feed))
                .where(Feed.owner_id == owner.id)
                .order_by(Item.id)
            )
            if not include_all:
                stmt = stmt.where(Item.decision.is_not(None))
            records = [_training_record(item) for item in session.scalars(stmt)]
    finally:
        engine.dispose()

    if not records:
        typer.echo(
            "No labelled items yet. Star or Keep/Drop a few in the reader first.",
            err=True,
        )
        return

    payload = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in records
    )
    if out is None:
        typer.echo(payload, nl=False)
        return

    target = out.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    typer.echo(f"Wrote {len(records)} item(s) to {target}")


@app.command()
def doctor(
    db: Annotated[Path | None, typer.Option(help="Path to the SQLite database.")] = None,
) -> None:
    """Check the database, Ollama, SerpAPI and Sentry setup."""
    settings = _load_settings(db)
    failures = 0

    engine = create_engine(settings)
    try:
        init_db(engine, settings)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            feed_count = session.scalar(select(func.count()).select_from(Feed)) or 0
            item_count = session.scalar(select(func.count()).select_from(Item)) or 0
            labelled = (
                session.scalar(
                    select(func.count())
                    .select_from(Item)
                    .where(Item.decision.is_not(None))
                )
                or 0
            )
        typer.echo(
            f"OK    database  {settings.database_label} "
            f"({feed_count} feeds, {item_count} items, {labelled} labelled)"
        )
    except Exception as exc:
        failures += 1
        typer.echo(
            f"FAIL  database  {settings.database_label}: {type(exc).__name__}",
            err=True,
        )
    finally:
        engine.dispose()

    ollama_label = "ollama cloud" if settings.ollama_cloud else "ollama"
    ollama_model = settings.active_ollama_model
    reachable, detail, installed = model.check_ollama(settings)
    if not reachable:
        hint = (
            "check OLLAMA_API_KEY and network access"
            if settings.ollama_cloud
            else "the AI boxes will fail"
        )
        typer.echo(
            f"WARN  {ollama_label:<12} {detail}; {hint}",
            err=True,
        )
    elif _model_installed(ollama_model, installed):
        typer.echo(f"OK    {ollama_label:<12} {ollama_model} ({detail})")
    elif settings.ollama_cloud:
        typer.echo(
            f"WARN  {ollama_label:<12} model {ollama_model!r} is not listed "
            "for this account; set OLLAMA_CLOUD_MODEL to the exact cloud tag",
            err=True,
        )
    else:
        typer.echo(
            f"WARN  {ollama_label:<12} model {ollama_model!r} is not installed; "
            f"run `ollama pull {ollama_model}`",
            err=True,
        )

    if settings.serpapi_api_key:
        typer.echo("OK    serpapi   key configured")
    else:
        typer.echo(
            "WARN  serpapi   SERPAPI_API_KEY is not set; the Search box is off",
            err=True,
        )

    if not settings.sentry_enabled:
        typer.echo("OK    sentry    disabled by SENTRY_ENABLED=false")
    elif not settings.sentry_active:
        typer.echo("OK    sentry    inactive (SENTRY_DSN not set; tracing off)")
    elif settings.sentry_traces_sample_rate > 0:
        typer.echo(
            "OK    sentry    tracing on "
            f"(environment={settings.sentry_environment}, "
            f"sample={settings.sentry_traces_sample_rate:g})"
        )
    else:
        typer.echo(
            "OK    sentry    errors on, tracing off "
            "(SENTRY_TRACES_SAMPLE_RATE=0)"
        )

    if failures:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    app()
