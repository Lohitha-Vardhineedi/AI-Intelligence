from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Db
from app.schemas.common import ApiResponse
from app.schemas.video import JobOut
from app.services import videos as service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: str, db: Db) -> ApiResponse[JobOut]:
    return ApiResponse(data=JobOut.model_validate(await service.get_job(db, job_id)))


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, db: Db) -> ApiResponse[JobOut]:
    job = await service.cancel_job(db, await service.get_job(db, job_id))
    return ApiResponse(data=JobOut.model_validate(job))
