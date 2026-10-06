"""Video upload and job control, as used by the API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError, NotFoundError
from app.events.types import new_id
from app.models import EventRecord, JobStatus, Video, VideoProcessingJob
from app.models.base import utcnow
from app.storage.local import LocalStorage
from app.video.sources import SUPPORTED_VIDEO_EXTENSIONS, VideoSourceError, probe_video

JobDispatcher = Callable[[str], None]


async def upload_video(
    db: AsyncSession, storage: LocalStorage, upload: UploadFile, *, max_bytes: int
) -> Video:
    filename = Path(upload.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_VIDEO_EXTENSIONS:
        raise AppError(
            "VIDEO_FORMAT_UNSUPPORTED",
            "Unsupported file type. Upload an MP4, AVI, MOV or MKV video.",
            422,
        )
    too_large = AppError(
        "VIDEO_TOO_LARGE", f"The video is larger than {max_bytes // 2**20} MB.", 413
    )
    if upload.size is not None and upload.size > max_bytes:
        raise too_large

    video_id = new_id()
    folder = f"videos/{video_id}"
    key = f"{folder}/original{extension}"
    size = await run_in_threadpool(storage.save, key, upload.file)
    try:
        if size > max_bytes:
            raise too_large
        info = await run_in_threadpool(probe_video, storage.path(key))
    except VideoSourceError as exc:
        storage.delete(folder)
        raise AppError("VIDEO_FORMAT_UNSUPPORTED", str(exc), 422) from exc
    except AppError:
        storage.delete(folder)
        raise

    video = Video(
        id=video_id,
        filename=filename[:255],
        storage_key=key,
        size_bytes=size,
        format=extension.lstrip("."),
        duration_seconds=round(info.duration_s, 2),
        fps=round(info.fps, 3),
        width=info.width,
        height=info.height,
        frame_count=info.frame_count,
        jobs=[],
    )
    db.add(video)
    await db.commit()
    return video


async def list_videos(db: AsyncSession, page: int, page_size: int) -> tuple[list[Video], int]:
    total = await db.scalar(select(func.count()).select_from(Video)) or 0
    videos = await db.scalars(
        select(Video)
        .options(selectinload(Video.jobs))
        .order_by(Video.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(videos), total


async def get_video(db: AsyncSession, video_id: str) -> Video:
    video = await db.scalar(
        select(Video).options(selectinload(Video.jobs)).where(Video.id == video_id)
    )
    if video is None:
        raise NotFoundError("Video")
    return video


async def get_job(db: AsyncSession, job_id: str) -> VideoProcessingJob:
    job = await db.get(VideoProcessingJob, job_id)
    if job is None:
        raise NotFoundError("Job")
    return job


async def start_processing(
    db: AsyncSession, video: Video, dispatch: JobDispatcher
) -> VideoProcessingJob:
    if any(job.status.is_active for job in video.jobs):
        raise AppError("JOB_ALREADY_RUNNING", "This video is already being processed.", 409)
    job = VideoProcessingJob(video_id=video.id, status=JobStatus.QUEUED)
    db.add(job)
    await db.commit()
    dispatch(job.id)  # after the commit, so the worker can see the job
    return job


async def cancel_job(db: AsyncSession, job: VideoProcessingJob) -> VideoProcessingJob:
    if job.status is JobStatus.QUEUED:
        job.status = JobStatus.CANCELLED
        job.completed_at = utcnow()
    elif job.status is JobStatus.PROCESSING:
        job.cancel_requested = True  # the worker stops at its next progress update
    else:
        raise AppError("JOB_NOT_RUNNING", "This job has already finished.", 409)
    await db.commit()
    return job


async def delete_video(db: AsyncSession, storage: LocalStorage, video: Video) -> None:
    if any(job.status.is_active for job in video.jobs):
        raise AppError("JOB_ALREADY_RUNNING", "Cancel processing before deleting the video.", 409)
    folders = [f"videos/{video.id}", *(f"jobs/{job.id}" for job in video.jobs)]
    await db.delete(video)
    await db.commit()
    for folder in folders:
        storage.delete(folder)


async def list_events(
    db: AsyncSession,
    *,
    job_id: str | None,
    video_id: str | None,
    event_type: str | None,
    page: int,
    page_size: int,
) -> tuple[list[EventRecord], int]:
    query = select(EventRecord)
    if job_id:
        query = query.where(EventRecord.job_id == job_id)
    if video_id:
        query = query.where(EventRecord.video_id == video_id)
    if event_type:
        query = query.where(EventRecord.event_type == event_type)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    events = await db.scalars(
        query.order_by(EventRecord.video_timestamp_ms, EventRecord.frame_index)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(events), total


async def get_event(db: AsyncSession, event_id: str) -> EventRecord:
    event = await db.get(EventRecord, event_id)
    if event is None:
        raise NotFoundError("Event")
    return event
