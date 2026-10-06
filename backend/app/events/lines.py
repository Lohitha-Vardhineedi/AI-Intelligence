"""Line crossing with direction.

For a line drawn from A to B, crossing from its left-hand side to its right-hand side
(as seen on screen) is IN, and the opposite is OUT.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.ai.classes import expand_classes
from app.ai.types import Frame
from app.events.factory import EventFactory
from app.events.geometry import Point, segments_intersect, side_of_line
from app.events.track_state import TrackUpdate
from app.events.types import Event, EventType
from app.schemas.scene import LineConfig, LineDirection


@dataclass(slots=True)
class _TrackLineState:
    stable_side: int = 0  # side the track is confirmed to be on: -1 or +1
    anchor: Point | None = None  # last position seen on the stable side
    pending_side: int = 0
    pending_count: int = 0
    last_crossing_s: float = -math.inf


class LineCrossingDetector:
    def __init__(
        self,
        line: LineConfig,
        factory: EventFactory,
        *,
        confirm_frames: int = 2,
        tolerance: float = 0.005,
        min_interval_s: float = 1.0,
    ) -> None:
        """
        confirm_frames: frames the object must stay on the new side (stops jitter).
        tolerance: band around the line, in normalised units, that counts as "on the line".
        min_interval_s: ignore repeat crossings by the same track within this time.
        """
        self.line = line
        self._factory = factory
        self._a: Point = line.start
        self._b: Point = line.end
        self._classes = expand_classes(line.classes)
        self._confirm_frames = confirm_frames
        self._tolerance = tolerance
        self._min_interval_s = min_interval_s
        self._states: dict[int, _TrackLineState] = {}
        self.in_count = 0
        self.out_count = 0

    def process(self, frame: Frame, update: TrackUpdate) -> list[Event]:
        events: list[Event] = []
        for track in update.active:
            if self._classes and track.object_class not in self._classes:
                continue
            state = self._states.setdefault(track.track_id, _TrackLineState())
            side = side_of_line(self._a, self._b, track.position, self._tolerance)
            if side == 0:
                continue  # on the line: wait until it is clearly on one side
            if state.stable_side == 0:
                state.stable_side, state.anchor = side, track.position
                continue
            if side == state.stable_side:
                state.anchor = track.position
                state.pending_side = state.pending_count = 0
                continue

            if state.pending_side != side:
                state.pending_side, state.pending_count = side, 0
            state.pending_count += 1
            if state.pending_count < self._confirm_frames:
                continue

            assert state.anchor is not None
            crossed = segments_intersect(state.anchor, track.position, self._a, self._b)
            from_side = state.stable_side
            state.stable_side, state.anchor = side, track.position
            state.pending_side = state.pending_count = 0
            # Changing sides without crossing the segment means walking around its end.
            if not crossed or frame.timestamp_s - state.last_crossing_s < self._min_interval_s:
                continue
            state.last_crossing_s = frame.timestamp_s

            direction = LineDirection.IN if from_side < 0 < side else LineDirection.OUT
            if direction is LineDirection.IN:
                self.in_count += 1
            else:
                self.out_count += 1
            if self.line.direction not in (LineDirection.BOTH, direction):
                continue

            common = {
                "track": track,
                "line_id": self.line.id,
                "line_name": self.line.name,
                "direction": direction.value,
            }
            events.append(self._factory.from_frame(EventType.LINE_CROSSED, frame, **common))
            if track.object_class == "person":
                person_event = (
                    EventType.PERSON_ENTERED if direction is LineDirection.IN
                    else EventType.PERSON_EXITED
                )
                events.append(self._factory.from_frame(person_event, frame, **common))

        for track in update.lost:
            self._states.pop(track.track_id, None)
        return events
