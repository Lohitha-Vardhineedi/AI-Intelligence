from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.ai.types import BoundingBox


class EventType(StrEnum):
    PERSON_DETECTED = "PERSON_DETECTED"
    OBJECT_DETECTED = "OBJECT_DETECTED"
    PERSON_ENTERED = "PERSON_ENTERED"
    PERSON_EXITED = "PERSON_EXITED"
    LINE_CROSSED = "LINE_CROSSED"
    ZONE_ENTERED = "ZONE_ENTERED"
    ZONE_EXITED = "ZONE_EXITED"
    INTRUSION_DETECTED = "INTRUSION_DETECTED"
    CROWD_DETECTED = "CROWD_DETECTED"
    LOITERING_DETECTED = "LOITERING_DETECTED"
    OBJECT_COUNT_THRESHOLD = "OBJECT_COUNT_THRESHOLD"
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
    CAMERA_ONLINE = "CAMERA_ONLINE"
    PROCESSING_STARTED = "PROCESSING_STARTED"
    PROCESSING_COMPLETED = "PROCESSING_COMPLETED"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReferencePoint(StrEnum):
    """Which point of a box is tested against lines and zones."""

    BOTTOM_CENTER = "bottom_center"  # feet or wheels: matches lines drawn on the floor
    CENTER = "center"


DEFAULT_SEVERITY: dict[EventType, Severity] = {
    EventType.PERSON_DETECTED: Severity.INFO,
    EventType.OBJECT_DETECTED: Severity.INFO,
    EventType.LINE_CROSSED: Severity.INFO,
    EventType.PERSON_ENTERED: Severity.LOW,
    EventType.PERSON_EXITED: Severity.LOW,
    EventType.ZONE_ENTERED: Severity.LOW,
    EventType.ZONE_EXITED: Severity.LOW,
    EventType.INTRUSION_DETECTED: Severity.HIGH,
    EventType.CROWD_DETECTED: Severity.MEDIUM,
    EventType.LOITERING_DETECTED: Severity.MEDIUM,
    EventType.OBJECT_COUNT_THRESHOLD: Severity.MEDIUM,
    EventType.CAMERA_OFFLINE: Severity.HIGH,
    EventType.CAMERA_ONLINE: Severity.INFO,
    EventType.PROCESSING_STARTED: Severity.INFO,
    EventType.PROCESSING_COMPLETED: Severity.INFO,
    EventType.PROCESSING_FAILED: Severity.MEDIUM,
}


def new_id() -> str:
    """Time-ordered UUIDv7 on Python 3.14+, UUIDv4 on older versions."""
    return str(getattr(uuid, "uuid7", uuid.uuid4)())


@dataclass(slots=True)
class Event:
    event_type: EventType
    severity: Severity
    camera_id: str
    occurred_at: datetime
    stream_time_s: float
    frame_index: int
    event_id: str = field(default_factory=new_id)
    track_id: int | None = None
    object_class: str | None = None
    confidence: float | None = None
    bbox: BoundingBox | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    line_id: str | None = None
    line_name: str | None = None
    direction: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    snapshot_path: str | None = None

    @property
    def title(self) -> str:
        """Short description for SMS, logs and overlays."""
        cls = (self.object_class or "object").capitalize()
        zone = self.zone_name or "zone"
        match self.event_type:
            case EventType.INTRUSION_DETECTED:
                if self.object_class == "person":
                    return "Unauthorized Person Entry"
                return f"Unauthorized {cls} in {zone}"
            case EventType.PERSON_ENTERED:
                return "Person Entered"
            case EventType.PERSON_EXITED:
                return "Person Exited"
            case EventType.LINE_CROSSED:
                return f"{cls} crossed {self.line_name or 'line'} ({self.direction})"
            case EventType.ZONE_ENTERED:
                return f"{cls} entered {zone}"
            case EventType.ZONE_EXITED:
                return f"{cls} left {zone}"
            case EventType.LOITERING_DETECTED:
                return f"Loitering in {zone}"
            case EventType.CROWD_DETECTED:
                where = f" in {self.zone_name}" if self.zone_name else ""
                return f"Crowd detected{where} ({self.details.get('count')} people)"
            case EventType.OBJECT_COUNT_THRESHOLD:
                return f"{cls} count above limit ({self.details.get('count')})"
            case EventType.PERSON_DETECTED:
                return "Person detected"
            case EventType.OBJECT_DETECTED:
                return f"{cls} detected"
            case _:
                return self.event_type.replace("_", " ").capitalize()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "camera_id": self.camera_id,
            "occurred_at": self.occurred_at.isoformat(),
            "stream_time_s": round(self.stream_time_s, 3),
            "frame_index": self.frame_index,
            "track_id": self.track_id,
            "class": self.object_class,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "line_id": self.line_id,
            "line_name": self.line_name,
            "direction": self.direction,
            "details": self.details,
            "snapshot_path": self.snapshot_path,
        }


@dataclass(slots=True)
class Alert:
    rule_id: str
    rule_name: str
    severity: Severity
    event: Event
    created_at: datetime
    stream_time_s: float
    notify_sms: bool = False
    alert_id: str = field(default_factory=new_id)
    occurrence_count: int = 1  # matching events folded into this alert during the cooldown
    last_occurred_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "title": self.event.title,
            "event_id": self.event.event_id,
            "event_type": self.event.event_type.value,
            "track_id": self.event.track_id,
            "zone_name": self.event.zone_name,
            "created_at": self.created_at.isoformat(),
            "stream_time_s": round(self.stream_time_s, 3),
            "occurrence_count": self.occurrence_count,
            "last_occurred_at": (
                self.last_occurred_at.isoformat() if self.last_occurred_at else None
            ),
            "snapshot_path": self.event.snapshot_path,
        }
