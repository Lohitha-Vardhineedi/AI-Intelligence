from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class EventRecord(Base):
    """An event found while processing a video. The ID is the one the engine assigned."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_job_time", "job_id", "video_timestamp_ms"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("video_processing_jobs.id", ondelete="CASCADE"))
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    video_timestamp_ms: Mapped[int] = mapped_column(Integer)
    frame_index: Mapped[int] = mapped_column(Integer)
    track_id: Mapped[int | None] = mapped_column(Integer)
    object_class: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[dict[str, int] | None] = mapped_column(JSON)
    zone_id: Mapped[str | None] = mapped_column(String(64))
    zone_name: Mapped[str | None] = mapped_column(String(255))
    line_id: Mapped[str | None] = mapped_column(String(64))
    line_name: Mapped[str | None] = mapped_column(String(255))
    direction: Mapped[str | None] = mapped_column(String(8))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    snapshot_key: Mapped[str | None] = mapped_column(String(512))
