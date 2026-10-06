from __future__ import annotations

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import AppSettings, Db, Dispatcher, Storage
from app.core.errors import NotFoundError
from app.schemas.common import ApiResponse, PagedResponse, Pagination
from app.schemas.video import JobOut, VideoOut
from app.services import videos as service

router = APIRouter(prefix="/videos", tags=["videos"])

_MEDIA_TYPES = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
}


@router.post("/upload", status_code=201)
async def upload_video(
    file: UploadFile, db: Db, storage: Storage, settings: AppSettings
) -> ApiResponse[VideoOut]:
    video = await service.upload_video(
        db, storage, file, max_bytes=settings.max_upload_mb * 2**20
    )
    return ApiResponse(data=VideoOut.from_model(video))


@router.get("")
async def list_videos(
    db: Db,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PagedResponse[VideoOut]:
    videos, total = await service.list_videos(db, page, page_size)
    return PagedResponse(
        data=[VideoOut.from_model(v) for v in videos],
        pagination=Pagination.of(page, page_size, total),
    )


@router.get("/{video_id}")
async def get_video(video_id: str, db: Db) -> ApiResponse[VideoOut]:
    return ApiResponse(data=VideoOut.from_model(await service.get_video(db, video_id)))


@router.delete("/{video_id}")
async def delete_video(video_id: str, db: Db, storage: Storage) -> ApiResponse[None]:
    await service.delete_video(db, storage, await service.get_video(db, video_id))
    return ApiResponse(data=None)


@router.post("/{video_id}/process", status_code=202)
async def process_video(video_id: str, db: Db, dispatch: Dispatcher) -> ApiResponse[JobOut]:
    video = await service.get_video(db, video_id)
    job = await service.start_processing(db, video, dispatch)
    return ApiResponse(data=JobOut.model_validate(job))


@router.get("/{video_id}/playback", response_class=FileResponse)
async def original_video(video_id: str, db: Db, storage: Storage) -> FileResponse:
    video = await service.get_video(db, video_id)
    return FileResponse(
        storage.path(video.storage_key),
        media_type=_MEDIA_TYPES.get(video.format, "application/octet-stream"),
        filename=video.filename,
        content_disposition_type="inline",
    )


@router.get("/{video_id}/annotated", response_class=FileResponse)
async def annotated_video(video_id: str, db: Db, storage: Storage) -> FileResponse:
    video = await service.get_video(db, video_id)
    job = next((j for j in video.jobs if j.annotated_video_key), None)
    if job is None or job.annotated_video_key is None:
        raise NotFoundError("Annotated video")
    return FileResponse(storage.path(job.annotated_video_key), media_type="video/mp4")
