from __future__ import annotations

from app.ai.types import Frame
from app.events.factory import EventFactory
from app.events.track_state import TrackUpdate
from app.events.types import Event, EventType


class ThresholdMonitor:
    """Fires once when a count stays above `threshold` for `min_duration_s`.

    It only re-arms after the count has been back at or below the threshold for
    `rearm_s`, so a count hovering around the limit doesn't fire again and again.
    """

    def __init__(self, threshold: int, min_duration_s: float, rearm_s: float = 2.0) -> None:
        self.threshold = threshold
        self._min_duration_s = min_duration_s
        self._rearm_s = rearm_s
        self._above_since: float | None = None
        self._below_since: float | None = None
        self.active = False

    def update(self, count: int, now: float) -> bool:
        if count > self.threshold:
            self._below_since = None
            if self._above_since is None:
                self._above_since = now
            if not self.active and now - self._above_since >= self._min_duration_s:
                self.active = True
                return True
            return False

        self._above_since = None
        if self.active:
            if self._below_since is None:
                self._below_since = now
            if now - self._below_since >= self._rearm_s:
                self.active = False
                self._below_since = None
        return False


class CountThresholdDetector:
    """Whole-frame limit: CROWD_DETECTED for people, OBJECT_COUNT_THRESHOLD otherwise."""

    def __init__(
        self, factory: EventFactory, *, object_class: str, max_count: int, min_duration_s: float
    ) -> None:
        self._factory = factory
        self._class = object_class
        self._monitor = ThresholdMonitor(max_count, min_duration_s)
        self._event_type = (
            EventType.CROWD_DETECTED if object_class == "person"
            else EventType.OBJECT_COUNT_THRESHOLD
        )

    def process(self, frame: Frame, update: TrackUpdate) -> list[Event]:
        count = sum(1 for t in update.active if t.object_class == self._class)
        if not self._monitor.update(count, frame.timestamp_s):
            return []
        return [
            self._factory.from_frame(
                self._event_type,
                frame,
                object_class=self._class,
                details={"count": count, "threshold": self._monitor.threshold},
            )
        ]
