from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Pixel coordinates: (x1, y1) top-left, (x2, y2) bottom-right."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    @property
    def bottom_center(self) -> tuple[float, float]:
        """Where a person or vehicle touches the ground."""
        return (self.x1 + self.x2) / 2, self.y2

    def to_dict(self) -> dict[str, int]:
        return {
            "x": round(self.x1),
            "y": round(self.y1),
            "width": round(self.width),
            "height": round(self.height),
        }


@dataclass(frozen=True, slots=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: BoundingBox


@dataclass(frozen=True, slots=True)
class TrackedObject:
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    bbox: BoundingBox


@dataclass(slots=True)
class Frame:
    image: np.ndarray
    index: int  # position in the source, counting skipped frames
    timestamp_s: float  # video position for files, time since start for streams
    captured_at: datetime  # wall-clock time, timezone-aware

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])
