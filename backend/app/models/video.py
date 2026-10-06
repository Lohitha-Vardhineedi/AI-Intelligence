from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, UTCDateTime


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_active(self) -> bool:
        return self in (JobStatus.QUEUED, JobStatus.PROCESSING)


class Video(IdMixin, TimestampMixin, Base):
    __tablename__ = "videos"

    filename: Mapped[str] = mapped_column(String(255))  # name as uploaded
    storage_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    format: Mapped[str] = mapped_column(String(16))
    duration_seconds: Mapped[float] = mapped_column(Float)
    fps: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    frame_count: Mapped[int] = mapped_column(Integer)

    jobs: Mapped[list[VideoProcessingJob]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VideoProcessingJob.created_at.desc()",
    )


class VideoProcessingJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "video_processing_jobs"

    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=16), default=JobStatus.QUEUED
    )
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0)
    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_frames: Mapped[int | None] = mapped_column(Integer)
    processing_fps: Mapped[float | None] = mapped_column(Float)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(64))
    output_key: Mapped[str | None] = mapped_column(String(512))
    annotated_video_key: Mapped[str | None] = mapped_column(String(512))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    video: Mapped[Video] = relationship(back_populates="jobs")
