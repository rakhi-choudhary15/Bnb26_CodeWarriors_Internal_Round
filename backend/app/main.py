"""FastAPI application factory (ARCHITECTURE.md §2).

Routers stay thin; this module owns the app's *shape*: middleware, exception
handlers, CORS, lifespan startup and the OpenAPI contract. The OpenAPI document
lives at `/api/openapi.json` because the TypeScript client is generated from it.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import errors
from app.api.routes import assets, creation, health, jobs, projects
from app.core.config import settings
from app.core.db import migrate_to_head
from app.core.jobs import get_queue
from app.core.logging import configure_logging, get_logger, log_event
from app.core.storage import get_storage
from app.workers.runners import available_handlers

logger = get_logger(__name__)

API_PREFIX = "/api"

DESCRIPTION = """
Intent-driven creation for short-form video.

Authenticate with `Authorization: Bearer <Supabase JWT>`; `/api/health` is the
only open route. Long-running work returns `202 {job_id}` — poll `GET /api/jobs/:id`.

Capabilities marked `mocked` or `stubbed` in a response are genuinely not
implemented; they will not improve at runtime.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    started = time.perf_counter()
    _startup_checks()
    # Touching the queue registers the worker handlers, so an in-process fallback
    # is ready before the first request arrives rather than on the first job.
    queue = get_queue()
    log_event(
        logger,
        "app.startup",
        environment=settings.app_env,
        demo_mode=settings.demo_mode,
        queue=queue.name,
        handlers=len(available_handlers()),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    yield
    log_event(logger, "app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="CreatorAI API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        # The generated client and /docs both live under /api so the whole app is
        # one origin behind a single proxy rule.
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "x-request-id"],
        expose_headers=["x-request-id", "x-response-time-ms", "retry-after", "location"],
    )
    errors.install(app)
    app.include_router(health.router)
    app.include_router(creation.router)
    app.include_router(projects.router)
    app.include_router(assets.router)
    app.include_router(jobs.router)
    return app


def _startup_checks() -> None:
    """Fail loudly on a broken configuration, quietly on a missing optional tool.

    A missing FFmpeg degrades the app to 'no rendering' rather than refusing to
    start: the demo path still needs intents, scripts and clips, and `/api/health`
    reports the gap. The schema is brought up to the latest Alembic revision on
    every dialect, so a clean checkout needs no separate migration step
    (AGENTS.md §21).
    """
    logger.info("Database schema: %s", migrate_to_head())
    get_storage()  # Fail now if storage is misconfigured, not on the first request.


app = create_app()
