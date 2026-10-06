"""Test builders: frames, tracked objects and scenes without a real model or video."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from app.ai.types import BoundingBox, Detection, Frame, TrackedObject
from app.notifications.sms import SMSProvider, SMSResult
from app.schemas.scene import SceneConfig

WIDTH, HEIGHT = 1000, 1000
T0 = datetime(2026, 10, 5, 10, 42, 0, tzinfo=UTC)


def make_frame(index: int, fps: float = 10.0) -> Frame:
    t = index / fps
    return Frame(
        image=np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8),
        index=index,
        timestamp_s=t,
        captured_at=T0 + timedelta(seconds=t),
    )


def box_at(foot_x: float, foot_y: float, w: float = 0.05, h: float = 0.2) -> BoundingBox:
    """Box whose bottom-centre (feet) is at the normalised point (foot_x, foot_y)."""
    x, y = foot_x * WIDTH, foot_y * HEIGHT
    return BoundingBox(x - w * WIDTH / 2, y - h * HEIGHT, x + w * WIDTH / 2, y)


def tracked(track_id: int, foot_x: float, foot_y: float, cls: str = "person",
            conf: float = 0.9) -> TrackedObject:
    return TrackedObject(track_id=track_id, class_id=0, class_name=cls, confidence=conf,
                         bbox=box_at(foot_x, foot_y))


def detection(foot_x: float, foot_y: float, cls: str = "person", class_id: int = 0,
              conf: float = 0.9) -> Detection:
    return Detection(class_id=class_id, class_name=cls, confidence=conf,
                     bbox=box_at(foot_x, foot_y))


def scene(**overrides: Any) -> SceneConfig:
    """A room zone on the right half (x > 0.5) and an entrance line at x = 0.5."""
    data: dict[str, Any] = {
        "camera": {"id": "cam-1", "name": "Camera 01", "location": "Room 101"},
        "tracking": {"min_hits": 2, "lost_timeout_seconds": 1.0},
        "zones": [{
            "id": "room", "name": "Room 101", "type": "RESTRICTED", "classes": ["person"],
            "severity": "CRITICAL", "min_frames_inside": 2, "min_frames_outside": 2,
            "points": [[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]],
        }],
        "lines": [{"id": "door", "name": "Door", "start": [0.5, 1.0], "end": [0.5, 0.0]}],
        "rules": [{
            "id": "intrusion", "name": "Person entering room",
            "event_types": ["INTRUSION_DETECTED"], "zones": ["room"],
            "object_classes": ["person"], "severity": "CRITICAL", "cooldown_seconds": 60,
        }],
    }
    data.update(overrides)
    return SceneConfig.model_validate(data)


class FakeSMSProvider(SMSProvider):
    name = "fake"

    def __init__(self, results: list[SMSResult] | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self._results = list(results or [])

    def send_sms(self, phone_number: str, message: str,
                 variables: Mapping[str, str] | None = None) -> SMSResult:
        self.sent.append((phone_number, message))
        if self._results:
            return self._results.pop(0)
        return SMSResult(True, self.name, message_id=f"m{len(self.sent)}")
