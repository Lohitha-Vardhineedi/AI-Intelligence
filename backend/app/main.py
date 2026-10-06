"""FastAPI app. Run from the backend folder with:

    alembic upgrade head
    uvicorn app.main:app --reload

API docs: http://localhost:8000/api/docs
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.services.video_jobs import fail_interrupted_jobs
from app.workers.dispatch import shutdown_local_worker, uses_celery

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Without Celery, jobs run inside this process, so any still marked as running were
    # cut off when it last stopped.
    if not uses_celery() and (count := await run_in_threadpool(fail_interrupted_jobs)):
        logger.warning("Marked %d interrupted job(s) as failed", count)
    yield
    await run_in_threadpool(shutdown_local_worker)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(
        title="AI Video Intelligence API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
