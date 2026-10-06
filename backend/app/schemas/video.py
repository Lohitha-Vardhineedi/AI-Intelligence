from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models import JobStatus, Video


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    status: JobStatus
    progress_percent: float
    frames_processed: int
    total_frames: int | None
    processing_fps: float | None
    cancel_requested: bool
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    model_version: str | None
    summary: dict[str, Any] | None
    created_at: datetime
    annotated_video_key: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_annotated_video(self) -> bool:
        return self.annotated_video_key is not None


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    size_bytes: int
    format: str
    duration_seconds: float
    fps: float
    width: int
    height: int
    frame_count: int
    created_at: datetime
    latest_job: JobOut | None = None

    @classmethod
    def from_model(cls, video: Video) -> VideoOut:
        out = cls.model_validate(video)
        out.latest_job = JobOut.model_validate(video.jobs[0]) if video.jobs else None
        return out


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    event_type: str
    severity: str
    title: str
    occurred_at: datetime
    video_timestamp_ms: int
    frame_index: int
    track_id: int | None
    object_class: str | None
    confidence: float | None
    bbox: dict[str, int] | None
    zone_name: str | None
    line_name: str | None
    direction: str | None
    details: dict[str, Any]
    snapshot_key: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_snapshot(self) -> bool:
        return self.snapshot_key is not None
