"""Zone entry and exit, restricted-area intrusion, loitering and zone crowding."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.classes import expand_classes
from app.ai.types import Frame
from app.events.crowd import ThresholdMonitor
from app.events.factory import EventFactory
from app.events.geometry import point_in_polygon
from app.events.track_state import TrackState, TrackUpdate
from app.events.types import Event, EventType, Severity
from app.schemas.scene import ZoneConfig, ZoneType


@dataclass(slots=True)
class _TrackZoneState:
    inside: bool = False
    in_streak: int = 0
    out_streak: int = 0
    entered_at_s: float = 0.0
    loitering_reported: bool = False


class ZoneDetector:
    def __init__(
        self, zone: ZoneConfig, factory: EventFactory, *, crowd_min_duration_s: float = 3.0
    ) -> None:
        self.zone = zone
        self._factory = factory
        self._polygon = list(zone.points)
        self._classes = expand_classes(zone.classes)
        self._allowed = expand_classes(zone.allowed_classes)
        self._labels = {"zone_id": zone.id, "zone_name": zone.name}
        self._states: dict[int, _TrackZoneState] = {}
        self._inside: dict[int, TrackState] = {}
        self._crowd = (
            ThresholdMonitor(zone.max_people, crowd_min_duration_s)
            if zone.max_people is not None
            else None
        )
        self.entries = 0
        self.exits = 0

    @property
    def occupancy(self) -> int:
        return len(self._inside)

    def process(self, frame: Frame, update: TrackUpdate) -> list[Event]:
        events: list[Event] = []
        now = frame.timestamp_s
        for track in update.active:
            if self._classes and track.object_class not in self._classes:
                continue
            state = self._states.setdefault(track.track_id, _TrackZoneState())
            # A few frames in a row on the new side, so jitter at the edge isn't an entry.
            if point_in_polygon(track.position, self._polygon):
                state.in_streak += 1
                state.out_streak = 0
                if not state.inside and state.in_streak >= self.zone.min_frames_inside:
                    events += self._enter(frame, track, state)
            else:
                state.out_streak += 1
                state.in_streak = 0
                if state.inside and state.out_streak >= self.zone.min_frames_outside:
                    events.append(self._exit(frame, track, state, reason="left"))

            if (
                state.inside
                and self.zone.max_dwell_seconds is not None
                and not state.loitering_reported
                and now - state.entered_at_s >= self.zone.max_dwell_seconds
            ):
                state.loitering_reported = True
                events.append(self._factory.from_frame(
                    EventType.LOITERING_DETECTED,
                    frame,
                    track=track,
                    details={
                        "dwell_seconds": round(now - state.entered_at_s, 1),
                        "max_dwell_seconds": self.zone.max_dwell_seconds,
                    },
                    **self._labels,
                ))

        for track in update.lost:
            state = self._states.pop(track.track_id, None)
            if state is not None and state.inside:
                events.append(self._exit(frame, track, state, reason="track_lost"))

        if self._crowd is not None:
            people = sum(1 for t in self._inside.values() if t.object_class == "person")
            if self._crowd.update(people, now):
                events.append(self._factory.from_frame(
                    EventType.CROWD_DETECTED,
                    frame,
                    object_class="person",
                    details={"count": people, "threshold": self.zone.max_people},
                    **self._labels,
                ))
        return events

    def _enter(self, frame: Frame, track: TrackState, state: _TrackZoneState) -> list[Event]:
        state.inside = True
        state.entered_at_s = frame.timestamp_s
        state.loitering_reported = False
        track.zone_ids.add(self.zone.id)
        self._inside[track.track_id] = track
        self.entries += 1
        events = [
            self._factory.from_frame(EventType.ZONE_ENTERED, frame, track=track, **self._labels)
        ]
        if self.zone.type is ZoneType.RESTRICTED and track.object_class not in self._allowed:
            events.append(self._factory.from_frame(
                EventType.INTRUSION_DETECTED,
                frame,
                track=track,
                severity=self.zone.severity or Severity.HIGH,
                details={"zone_type": self.zone.type.value},
                **self._labels,
            ))
        return events

    def _exit(
        self, frame: Frame, track: TrackState, state: _TrackZoneState, *, reason: str
    ) -> Event:
        state.inside = False
        track.zone_ids.discard(self.zone.id)
        self._inside.pop(track.track_id, None)
        self.exits += 1
        return self._factory.from_frame(
            EventType.ZONE_EXITED,
            frame,
            track=track,
            details={
                "reason": reason,
                "dwell_seconds": round(track.last_seen_s - state.entered_at_s, 1),
            },
            **self._labels,
        )
