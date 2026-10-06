"""Hands a job to a Celery worker when REDIS_URL is set, otherwise to a thread in the API
process. The local thread runs one job at a time and needs no Redis."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings
from app.services.video_jobs import run_video_job, stop_running_jobs

logger = logging.getLogger(__name__)

_local_worker: ThreadPoolExecutor | None = None


def uses_celery() -> bool:
    return bool(get_settings().redis_url)


def dispatch_video_job(job_id: str) -> None:
    global _local_worker
    if uses_celery():
        from app.workers.tasks.video_processing import process_video

        process_video.delay(job_id)
        return
    if _local_worker is None:
        _local_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-job")
    _local_worker.submit(_run_and_log, job_id)


def shutdown_local_worker() -> None:
    """Stops the running job (it ends as CANCELLED) and drops queued ones."""
    if _local_worker is not None:
        stop_running_jobs()
        _local_worker.shutdown(wait=True, cancel_futures=True)


def _run_and_log(job_id: str) -> None:
    try:
        run_video_job(job_id)
    except Exception:  # an executor would otherwise swallow it silently
        logger.exception("Video job %s crashed", job_id)
