from __future__ import annotations

from app.services.video_jobs import run_video_job
from app.workers.celery_app import celery_app


@celery_app.task(name="videos.process")
def process_video(job_id: str) -> None:
    run_video_job(job_id)
