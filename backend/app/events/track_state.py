"""Per-track state shared by all event detectors.

The tracker gives each object an ID; the registry adds what the detectors need on top:
position in normalised coordinates, a stable class, confirmation and current zones.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.ai.types import BoundingBox, Frame, TrackedObject
from app.events.geometry import Point
from app.events.types import ReferencePoint


@dataclass(slots=True)
class TrackState:
    track_id: int
    bbox: BoundingBox
    position: Point  # normalised reference point, used for line and zone checks
    confidence: float
    last_seen_s: float
    object_class: str
    class_votes: Counter[str] = field(default_factory=Counter)
    strong_hits: int = 0  # detections at or above the confirmation threshold
    confirmed: bool = False
    zone_ids: set[str] = field(default_factory=set)

    def vote(self, class_name: str) -> None:
        """Majority vote over the track's history, so one odd frame can't flip its class."""
        self.class_votes[class_name] += 1
        if self.class_votes[class_name] > self.class_votes[self.object_class]:
            self.object_class = class_name


@dataclass(slots=True)
class TrackUpdate:
    active: list[TrackState]  # confirmed tracks visible in this frame
    confirmed_now: list[TrackState]  # tracks confirmed in this frame
    lost: list[TrackState]  # confirmed tracks that have disappeared


class TrackRegistry:
    """A track is confirmed (and counted) after `min_hits` detections at or above
    `confirm_threshold`, or its class's entry in `class_thresholds`. The tracker also passes
    on weak detections to bridge occlusions, but those never confirm a track on their own.
    """

    def __init__(
        self,
        *,
        min_hits: int = 3,
        confirm_threshold: float = 0.0,
        class_thresholds: Mapping[str, float] | None = None,
        lost_timeout_s: float = 1.5,
        reference_point: ReferencePoint = ReferencePoint.BOTTOM_CENTER,
    ) -> None:
        self._min_hits = min_hits
        self._confirm_threshold = confirm_threshold
        self._class_thresholds = dict(class_thresholds or {})
        self._lost_timeout_s = lost_timeout_s
        self._use_feet = reference_point is ReferencePoint.BOTTOM_CENTER
        self._tracks: dict[int, TrackState] = {}

    def _reference(self, bbox: BoundingBox, width: int, height: int) -> Point:
        x, y = bbox.bottom_center if self._use_feet else bbox.center
        return min(max(x / width, 0.0), 1.0), min(max(y / height, 0.0), 1.0)

    def update(self, tracked: Sequence[TrackedObject], frame: Frame) -> TrackUpdate:
        now = frame.timestamp_s
        active: list[TrackState] = []
        confirmed_now: list[TrackState] = []

        for obj in tracked:
            position = self._reference(obj.bbox, frame.width, frame.height)
            state = self._tracks.get(obj.track_id)
            if state is None:
                state = TrackState(
                    track_id=obj.track_id,
                    bbox=obj.bbox,
                    position=position,
                    confidence=obj.confidence,
                    last_seen_s=now,
                    object_class=obj.class_name,
                )
                self._tracks[obj.track_id] = state
            else:
                state.bbox = obj.bbox
                state.position = position
                state.confidence = obj.confidence
                state.last_seen_s = now
            state.vote(obj.class_name)

            threshold = self._class_thresholds.get(obj.class_name, self._confirm_threshold)
            if obj.confidence >= threshold:
                state.strong_hits += 1
            if not state.confirmed and state.strong_hits >= self._min_hits:
                state.confirmed = True
                confirmed_now.append(state)
            if state.confirmed:
                active.append(state)

        expired = [
            track_id for track_id, state in self._tracks.items()
            if now - state.last_seen_s > self._lost_timeout_s
        ]
        lost = [state for state in map(self._tracks.pop, expired) if state.confirmed]
        return TrackUpdate(active=active, confirmed_now=confirmed_now, lost=lost)
