"""Outputs: annotated video, evidence snapshots and the event log (§15, §32, §62)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.events.types import Event

logger = logging.getLogger(__name__)


class AnnotatedVideoWriter:
    """Writes MP4. Tries H.264 first (plays in browsers), then MPEG-4 Part 2."""

    def __init__(self, path: Path, fps: float, size: tuple[int, int]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._writer: cv2.VideoWriter | None = None
        for codec in ("avc1", "mp4v"):
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
            if writer.isOpened():
                self._writer, self.codec = writer, codec
                break
            writer.release()
        if self._writer is None:
            raise RuntimeError(f"Could not create video writer for {path}")
        logger.info("Writing annotated video %s (codec %s)", path.name, self.codec)

    def write(self, image: np.ndarray) -> None:
        if self._writer is not None:
            self._writer.write(image)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


class SnapshotStore:
    """Saves an evidence JPEG for an event, with the object highlighted."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, event: Event, image: np.ndarray) -> str:
        evidence = image.copy()
        if event.bbox is not None:
            b = event.bbox
            cv2.rectangle(evidence, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)),
                          (40, 40, 230), 3)
        caption = f"{event.title} | {event.occurred_at:%Y-%m-%d %H:%M:%S}"
        if event.track_id is not None:
            caption += f" | track #{event.track_id}"
        cv2.rectangle(evidence, (0, 0), (evidence.shape[1], 30), (0, 0, 0), -1)
        cv2.putText(evidence, caption, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 1, cv2.LINE_AA)
        name = (
            f"{event.occurred_at:%Y%m%d_%H%M%S}_{event.event_type.value.lower()}"
            f"_t{event.track_id if event.track_id is not None else 'na'}"
            f"_{event.event_id[-6:]}.jpg"
        )
        path = self._dir / name
        cv2.imwrite(str(path), evidence)
        return str(path)


class EventLogWriter:
    """Appends every event as one JSON line (events.jsonl)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._file = path.open("w", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._file.write(json.dumps(record, default=str) + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            self._file.close()
