from __future__ import annotations

from collections import Counter, defaultdict

from app.ai.types import Frame
from app.events.factory import EventFactory
from app.events.track_state import TrackUpdate
from app.events.types import Event, EventType


class ObjectCounter:
    """Counts objects visible now, unique objects and the peak at once, per class.

    Only confirmed tracks are counted, so a one-frame false detection is ignored and a
    person who stays in view is counted once.
    """

    def __init__(self, factory: EventFactory) -> None:
        self._factory = factory
        self.current: Counter[str] = Counter()
        self.peak: Counter[str] = Counter()
        self._unique: defaultdict[str, set[int]] = defaultdict(set)

    @property
    def unique(self) -> dict[str, int]:
        return {cls: len(ids) for cls, ids in sorted(self._unique.items())}

    def process(self, frame: Frame, update: TrackUpdate) -> list[Event]:
        self.current = Counter(track.object_class for track in update.active)
        for cls, count in self.current.items():
            if count > self.peak[cls]:
                self.peak[cls] = count

        events: list[Event] = []
        for track in update.confirmed_now:
            self._unique[track.object_class].add(track.track_id)
            event_type = (
                EventType.PERSON_DETECTED if track.object_class == "person"
                else EventType.OBJECT_DETECTED
            )
            events.append(self._factory.from_frame(event_type, frame, track=track))
        return events
