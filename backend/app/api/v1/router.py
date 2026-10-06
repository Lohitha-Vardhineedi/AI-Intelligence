from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import events, jobs, videos
from app.schemas.common import ApiResponse
from app.workers.dispatch import uses_celery

api_router = APIRouter()
api_router.include_router(videos.router)
api_router.include_router(jobs.router)
api_router.include_router(events.router)


@api_router.get("/health", tags=["system"])
async def health() -> ApiResponse[dict[str, str]]:
    return ApiResponse(data={"status": "ok", "jobs": "celery" if uses_celery() else "local"})
