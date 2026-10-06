"""Videos, processing jobs and events

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=False),
        sa.Column("fps", sa.Float, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("frame_count", sa.Integer, nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "video_processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("video_id", sa.String(36),
                  sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress_percent", sa.Float, nullable=False),
        sa.Column("frames_processed", sa.Integer, nullable=False),
        sa.Column("total_frames", sa.Integer),
        sa.Column("processing_fps", sa.Float),
        sa.Column("cancel_requested", sa.Boolean, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("model_version", sa.String(64)),
        sa.Column("output_key", sa.String(512)),
        sa.Column("annotated_video_key", sa.String(512)),
        sa.Column("summary", sa.JSON),
        *_timestamps(),
    )
    op.create_index("ix_video_processing_jobs_video_id", "video_processing_jobs", ["video_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36),
                  sa.ForeignKey("video_processing_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("video_id", sa.String(36),
                  sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("video_timestamp_ms", sa.Integer, nullable=False),
        sa.Column("frame_index", sa.Integer, nullable=False),
        sa.Column("track_id", sa.Integer),
        sa.Column("object_class", sa.String(32)),
        sa.Column("confidence", sa.Float),
        sa.Column("bbox", sa.JSON),
        sa.Column("zone_id", sa.String(64)),
        sa.Column("zone_name", sa.String(255)),
        sa.Column("line_id", sa.String(64)),
        sa.Column("line_name", sa.String(255)),
        sa.Column("direction", sa.String(8)),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("snapshot_key", sa.String(512)),
    )
    op.create_index("ix_events_job_time", "events", ["job_id", "video_timestamp_ms"])
    op.create_index("ix_events_video_id", "events", ["video_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("video_processing_jobs")
    op.drop_table("videos")
