"""Turns tracked objects into scene events. It knows nothing about rules, alerts or SMS."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import tzinfo

from app.ai.classes import expand_classes
from app.ai.types import Frame, TrackedObject
from app.events.counting import ObjectCounter
from app.events.crowd import CountThresholdDetector
from app.events.factory import EventFactory
from app.events.lines import LineCrossingDetector
from app.events.track_state import TrackRegistry, TrackState
from app.events.types import Event
from app.events.zones import ZoneDetector
from app.schemas.scene import SceneConfig


@dataclass(slots=True)
class SceneSnapshot:
    """Scene state after a frame, for the overlay."""

    tracks: list[TrackState]
    current_counts: Counter[str]
    unique_counts: dict[str, int]
    zone_occupancy: dict[str, int]
    line_counts: dict[str, tuple[int, int]]  # line id -> (IN, OUT)


@dataclass(slots=True)
class FrameAnalysis:
    frame: Frame
    events: list[Event] = field(default_factory=list)
    snapshot: SceneSnapshot | None = None


class EventDetector:
    def __init__(self, scene: SceneConfig, tz: tzinfo, *, confirm_threshold: float = 0.0) -> None:
        """confirm_threshold: confidence a detection needs to count towards confirming a
        track. Normally the detector's confidence threshold."""
        self.factory = EventFactory(scene.camera.id, tz)
        class_thresholds = {
            cls: value
            for name, value in scene.detection.class_confidence.items()
            for cls in expand_classes([name])
        }
        self.registry = TrackRegistry(
            min_hits=scene.tracking.min_hits,
            confirm_threshold=confirm_threshold,
            class_thresholds=class_thresholds,
            # A little longer than the tracker's own buffer, so a track the tracker
            # recovers keeps its history and isn't counted again.
            lost_timeout_s=scene.tracking.lost_timeout_seconds + 0.5,
            reference_point=scene.tracking.reference_point,
        )
        self.counter = ObjectCounter(self.factory)
        self.lines = [LineCrossingDetector(ln, self.factory) for ln in scene.lines if ln.enabled]
        self.zones = [ZoneDetector(z, self.factory) for z in scene.zones if z.enabled]
        limits = [(t.object_class, t.max_count, t.min_duration_seconds)
                  for t in scene.object_thresholds]
        if scene.crowd is not None:
            limits.append(("person", scene.crowd.max_people, scene.crowd.min_duration_seconds))
        self.thresholds = [
            CountThresholdDetector(
                self.factory, object_class=cls, max_count=count, min_duration_s=duration
            )
            for cls, count, duration in limits
        ]

    def process(self, frame: Frame, tracked: Sequence[TrackedObject]) -> FrameAnalysis:
        update = self.registry.update(tracked, frame)
        events = self.counter.process(frame, update)
        for detector in (*self.lines, *self.zones, *self.thresholds):
            events += detector.process(frame, update)
        return FrameAnalysis(frame=frame, events=events, snapshot=self._snapshot(update.active))

    def _snapshot(self, active: list[TrackState]) -> SceneSnapshot:
        return SceneSnapshot(
            tracks=active,
            current_counts=self.counter.current,
            unique_counts=self.counter.unique,
            zone_occupancy={z.zone.id: z.occupancy for z in self.zones},
            line_counts={ln.line.id: (ln.in_count, ln.out_count) for ln in self.lines},
        )
