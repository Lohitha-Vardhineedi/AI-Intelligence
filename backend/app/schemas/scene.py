"""Scene configuration (camera, zones, lines, alert rules), validated on load.

The engine only sees these models, so the same code works whether the config comes from
a YAML file, an API or a database."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.events.geometry import polygon_is_simple
from app.events.types import EventType, ReferencePoint, Severity

Coordinate = Annotated[float, Field(ge=0.0, le=1.0)]
NormPoint = tuple[Coordinate, Coordinate]
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ZoneType(StrEnum):
    RESTRICTED = "RESTRICTED"
    SAFE = "SAFE"
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    PARKING = "PARKING"
    CROWDED = "CROWDED"
    CUSTOM = "CUSTOM"


class LineDirection(StrEnum):
    IN = "IN"
    OUT = "OUT"
    BOTH = "BOTH"


class DedupScope(StrEnum):
    TRACK = "track"  # one alert per tracked object
    ZONE = "zone"  # one alert per zone/line (robust when a person gets a new track ID)
    CAMERA = "camera"
    RULE = "rule"


class Weekday(StrEnum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


_WEEKDAYS = list(Weekday)


class CameraConfig(_Model):
    id: Identifier = "camera-01"
    name: str = "Camera 01"
    location: str = ""


class DetectionConfig(_Model):
    # COCO class names or groups: person, vehicle, animal, bag. Empty list = everything.
    classes: list[str] = Field(default_factory=lambda: ["person", "vehicle", "animal", "bag"])
    confidence_threshold: float | None = Field(default=None, ge=0.05, le=0.99)
    # Stricter thresholds for classes that cause false alarms, e.g. {animal: 0.6}.
    class_confidence: dict[str, Annotated[float, Field(ge=0.05, le=0.99)]] = Field(
        default_factory=dict
    )
    iou_threshold: float | None = Field(default=None, ge=0.05, le=0.95)
    inference_fps: float | None = Field(default=10.0, gt=0, le=60)
    frame_skip: int | None = Field(default=None, ge=0, le=100)  # frames skipped between analyses


class TrackingConfig(_Model):
    min_hits: int = Field(default=3, ge=1, le=30)  # frames before an object is counted
    lost_timeout_seconds: float = Field(default=1.5, gt=0, le=30)
    reference_point: ReferencePoint = ReferencePoint.BOTTOM_CENTER


class ZoneConfig(_Model):
    id: Identifier
    name: str
    type: ZoneType = ZoneType.CUSTOM
    points: list[NormPoint] = Field(min_length=3, max_length=50)
    classes: list[str] = Field(default_factory=list)  # monitored classes; empty = all
    allowed_classes: list[str] = Field(default_factory=list)  # RESTRICTED zones only
    max_people: int | None = Field(default=None, ge=0)
    max_dwell_seconds: float | None = Field(default=None, gt=0)
    severity: Severity | None = None  # of intrusions into this zone
    min_frames_inside: int = Field(default=3, ge=1)
    min_frames_outside: int = Field(default=3, ge=1)
    enabled: bool = True

    @field_validator("points")
    @classmethod
    def _simple_polygon(cls, points: list[NormPoint]) -> list[NormPoint]:
        if not polygon_is_simple(points):
            raise ValueError("zone polygon edges must not cross each other")
        return points


class LineConfig(_Model):
    id: Identifier
    name: str
    start: NormPoint  # point A
    end: NormPoint  # point B. IN = crossing from the left of A->B to its right.
    direction: LineDirection = LineDirection.BOTH  # which crossings raise events
    classes: list[str] = Field(default_factory=list)  # empty = all
    enabled: bool = True

    @model_validator(mode="after")
    def _distinct_points(self) -> LineConfig:
        if self.start == self.end:
            raise ValueError("line start and end must be different points")
        return self


class CrowdConfig(_Model):
    max_people: int = Field(ge=1)
    min_duration_seconds: float = Field(default=3.0, ge=0)


class ObjectThresholdConfig(_Model):
    object_class: str
    max_count: int = Field(ge=0)
    min_duration_seconds: float = Field(default=3.0, ge=0)


class PrivacyMaskConfig(_Model):
    name: str
    points: list[NormPoint] = Field(min_length=3, max_length=50)


class ScheduleConfig(_Model):
    days: list[Weekday] = Field(default_factory=lambda: list(Weekday), min_length=1)
    start: time = time(0, 0)
    end: time = time(23, 59, 59)

    def is_active(self, local_time: datetime) -> bool:
        """Overnight windows (e.g. 22:00-06:00) belong to the day they start on."""
        day = _WEEKDAYS[local_time.weekday()]
        now = local_time.time()
        if self.start <= self.end:
            return day in self.days and self.start <= now <= self.end
        if now >= self.start:
            return day in self.days
        if now <= self.end:
            return _WEEKDAYS[(local_time - timedelta(days=1)).weekday()] in self.days
        return False


class RuleActions(_Model):
    sms: bool = True
    snapshot: bool = True


class AlertRuleConfig(_Model):
    id: Identifier
    name: str
    enabled: bool = True
    event_types: list[EventType] = Field(min_length=1)
    zones: list[str] = Field(default_factory=list)  # empty = any
    lines: list[str] = Field(default_factory=list)
    object_classes: list[str] = Field(default_factory=list)
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    schedule: ScheduleConfig | None = None
    severity: Severity | None = None  # None = use the event's severity
    actions: RuleActions = Field(default_factory=RuleActions)
    cooldown_seconds: float = Field(default=60.0, ge=0)
    dedup_scope: DedupScope = DedupScope.ZONE
    recipients: list[str] = Field(default_factory=list)  # empty = SMS_RECIPIENTS from .env


class SceneConfig(_Model):
    camera: CameraConfig = Field(default_factory=CameraConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    zones: list[ZoneConfig] = Field(default_factory=list)
    lines: list[LineConfig] = Field(default_factory=list)
    crowd: CrowdConfig | None = None
    object_thresholds: list[ObjectThresholdConfig] = Field(default_factory=list)
    privacy_masks: list[PrivacyMaskConfig] = Field(default_factory=list)
    rules: list[AlertRuleConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> SceneConfig:
        for label, items in (("zone", self.zones), ("line", self.lines), ("rule", self.rules)):
            ids = [item.id for item in items]
            duplicates = {i for i in ids if ids.count(i) > 1}
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {sorted(duplicates)}")
        zone_ids = {z.id for z in self.zones}
        line_ids = {ln.id for ln in self.lines}
        for rule in self.rules:
            if missing := set(rule.zones) - zone_ids:
                raise ValueError(f"rule '{rule.id}' references unknown zones {sorted(missing)}")
            if missing := set(rule.lines) - line_ids:
                raise ValueError(f"rule '{rule.id}' references unknown lines {sorted(missing)}")
        return self


def load_scene_config(path: Path) -> SceneConfig:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return SceneConfig.model_validate(data)
