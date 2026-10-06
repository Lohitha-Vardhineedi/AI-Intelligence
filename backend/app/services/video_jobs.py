"""Runs one video processing job: the analysis pipeline, progress, cancellation and
results. Called by the Celery task, or by the API's local worker thread."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.database import sync_session_factory
from app.models import EventRecord, JobStatus, Video, VideoProcessingJob
from app.models.base import utcnow
from app.schemas.scene import load_scene_config
from app.services.video_analysis import AnalysisOptions, AnalysisSession, build_analysis
from app.storage.local import LocalStorage, get_storage
from app.video.pipeline import PipelineProgress, RunStatus, RunSummary, VideoPipeline

logger = logging.getLogger(__name__)

_FINAL_STATUS = {
    RunStatus.COMPLETED: JobStatus.COMPLETED,
    RunStatus.FAILED: JobStatus.FAILED,
    RunStatus.CANCELLED: JobStatus.CANCELLED,
    RunStatus.STOPPED: JobStatus.CANCELLED,
}
_shutting_down = threading.Event()


def stop_running_jobs() -> None:
    """Running jobs stop at their next progress update. Used when the API shuts down."""
    _shutting_down.set()


class _ProgressReporter:
    """Saves progress on the job row and stops the pipeline when cancellation is requested."""

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id
        self.pipeline: VideoPipeline | None = None

    def __call__(self, progress: PipelineProgress) -> None:
        with sync_session_factory()() as db:
            job = db.get(VideoProcessingJob, self._job_id)
            if job is None:
                stop = True
            else:
                job.progress_percent = round(progress.percent or 0.0, 1)
                job.frames_processed = progress.frames_read
                job.processing_fps = round(progress.processing_fps, 2)
                db.commit()
                stop = job.cancel_requested
        if (stop or _shutting_down.is_set()) and self.pipeline is not None:
            self.pipeline.stop()


def run_video_job(job_id: str) -> None:
    settings = get_settings()
    storage = get_storage()
    with sync_session_factory()() as db:
        job = db.get(VideoProcessingJob, job_id)
        if job is None or job.status is not JobStatus.QUEUED:
            return  # deleted, or cancelled while it was waiting
        job.status = JobStatus.PROCESSING
        job.started_at = utcnow()
        job.total_frames = job.video.frame_count or None
        source = storage.path(job.video.storage_key)
        db.commit()

    reporter = _ProgressReporter(job_id)
    try:
        scene = load_scene_config(settings.resolve_path(settings.scene_config_path))
        session = build_analysis(
            settings,
            scene,
            AnalysisOptions(
                source=str(source),
                output_root=storage.path(f"jobs/{job_id}"),
                on_progress=reporter,
                progress_interval_s=1.0,
            ),
        )
    except Exception as exc:
        logger.exception("Could not start job %s", job_id)
        _fail(job_id, f"Could not start processing: {exc}")
        return

    reporter.pipeline = session.pipeline
    try:
        summary = session.pipeline.run()
    finally:
        session.close()
    try:
        _save_results(job_id, session, summary, storage)
    except Exception as exc:
        logger.exception("Could not save the results of job %s", job_id)
        _fail(job_id, f"Could not save results: {exc}")


def fail_interrupted_jobs() -> int:
    """Marks jobs left QUEUED or PROCESSING by a server that stopped as FAILED."""
    with sync_session_factory()() as db:
        jobs = db.query(VideoProcessingJob).filter(
            VideoProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING])
        ).all()
        for job in jobs:
            job.status = JobStatus.FAILED
            job.error_message = "Interrupted: the server stopped before processing finished"
            job.completed_at = utcnow()
        db.commit()
        return len(jobs)


def forget_missing_videos() -> int:
    """Deletes the records of videos whose files are gone. Hosts without persistent storage
    (such as Render's free plan) lose uploaded files on every restart."""
    storage = get_storage()
    with sync_session_factory()() as db:
        missing = [v for v in db.query(Video).all() if not storage.path(v.storage_key).exists()]
        for video in missing:
            for job in video.jobs:
                storage.delete(f"jobs/{job.id}")
            db.delete(video)
        db.commit()
        return len(missing)


def _fail(job_id: str, message: str) -> None:
    with sync_session_factory()() as db:
        job = db.get(VideoProcessingJob, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = message[:2000]
            job.completed_at = utcnow()
            db.commit()


def _save_results(
    job_id: str, session: AnalysisSession, summary: RunSummary, storage: LocalStorage
) -> None:
    status = _FINAL_STATUS[summary.status]
    events = list(_read_events(session.output_dir / "events.jsonl", storage))
    with sync_session_factory()() as db:
        job = db.get(VideoProcessingJob, job_id)
        if job is None:
            return
        job.status = status
        job.error_message = summary.error
        job.completed_at = utcnow()
        job.model_version = session.model_version
        job.frames_processed = summary.frames_read
        if status is JobStatus.COMPLETED:
            job.progress_percent = 100.0
        job.output_key = storage.key(session.output_dir)
        if summary.annotated_video is not None and summary.annotated_video.exists():
            job.annotated_video_key = storage.key(summary.annotated_video)
        job.summary = _public_summary(summary, session)
        db.add_all(EventRecord(job_id=job_id, video_id=job.video_id, **e) for e in events)
        db.commit()


def _public_summary(summary: RunSummary, session: AnalysisSession) -> dict[str, Any]:
    """The run summary without local file paths, which the API must not expose."""
    data = summary.to_dict()
    data.pop("annotated_video", None)
    for alert in data["alerts"]:
        alert.pop("snapshot_path", None)
    data["model"] = session.model_version
    data["notifications"] = [r.to_dict() for r in session.notifier.records]
    return data


def _read_events(path: Path, storage: LocalStorage) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            raw = json.loads(line)
            yield {
                "id": raw["event_id"],
                "event_type": raw["event_type"],
                "severity": raw["severity"],
                "title": raw["title"][:255],
                "occurred_at": datetime.fromisoformat(raw["occurred_at"]),
                "video_timestamp_ms": round(raw["stream_time_s"] * 1000),
                "frame_index": raw["frame_index"],
                "track_id": raw["track_id"],
                "object_class": raw["class"],
                "confidence": raw["confidence"],
                "bbox": raw["bbox"],
                "zone_id": raw["zone_id"],
                "zone_name": raw["zone_name"],
                "line_id": raw["line_id"],
                "line_name": raw["line_name"],
                "direction": raw["direction"],
                "details": raw["details"],
                "snapshot_key": storage.key(raw["snapshot_path"]) if raw["snapshot_path"] else None,
            }
