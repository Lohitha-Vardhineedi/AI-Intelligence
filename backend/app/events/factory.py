from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

from app.ai.types import Frame
from app.events.track_state import TrackState
from app.events.types import DEFAULT_SEVERITY, Event, EventType, Severity


class EventFactory:
    """Fills in the camera, time and track fields every event shares."""

    def __init__(self, camera_id: str, tz: tzinfo) -> None:
        self.camera_id = camera_id
        self._tz = tz

    def from_frame(
        self,
        event_type: EventType,
        frame: Frame,
        *,
        track: TrackState | None = None,
        severity: Severity | None = None,
        **fields: Any,
    ) -> Event:
        if track is not None:
            fields.setdefault("track_id", track.track_id)
            fields.setdefault("object_class", track.object_class)
            fields.setdefault("confidence", track.confidence)
            fields.setdefault("bbox", track.bbox)
        return Event(
            event_type=event_type,
            severity=severity or DEFAULT_SEVERITY[event_type],
            camera_id=self.camera_id,
            occurred_at=frame.captured_at,
            stream_time_s=frame.timestamp_s,
            frame_index=frame.index,
            **fields,
        )

    def system(
        self,
        event_type: EventType,
        *,
        stream_time_s: float = 0.0,
        frame_index: int = 0,
        details: dict[str, Any] | None = None,
    ) -> Event:
        """Events not tied to a frame: camera online/offline and processing status."""
        return Event(
            event_type=event_type,
            severity=DEFAULT_SEVERITY[event_type],
            camera_id=self.camera_id,
            occurred_at=datetime.now(self._tz),
            stream_time_s=stream_time_s,
            frame_index=frame_index,
            details=details or {},
        )
