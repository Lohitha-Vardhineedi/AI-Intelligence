"""Run outputs: annotated video, evidence snapshots and the event log."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.events.types import Event

logger = logging.getLogger(__name__)

# H.264 plays in browsers; MPEG-4 Part 2 is the fallback. pip builds of OpenCV can't
# encode H.264 through FFmpeg, but Windows has an encoder built in (Media Foundation).
_WRITER_BACKENDS = (
    ((cv2.CAP_MSMF, "avc1"),) if sys.platform == "win32" else ()
) + ((cv2.CAP_FFMPEG, "avc1"), (cv2.CAP_FFMPEG, "mp4v"))


class AnnotatedVideoWriter:
    def __init__(self, path: Path, fps: float, size: tuple[int, int]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._writer: cv2.VideoWriter | None = None
        for backend, codec in _WRITER_BACKENDS:
            writer = cv2.VideoWriter(str(path), backend, cv2.VideoWriter_fourcc(*codec), fps, size)
            if writer.isOpened():
                self._writer = writer
                logger.info("Writing annotated video %s (codec %s)", path.name, codec)
                break
            writer.release()
        if self._writer is None:
            raise RuntimeError(f"Could not create a video writer for {path}")

    def write(self, image: np.ndarray) -> None:
        if self._writer is not None:
            self._writer.write(image)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


class SnapshotStore:
    """Saves an evidence JPEG for an event, with the object outlined."""

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
        track = event.track_id if event.track_id is not None else "na"
        name = (
            f"{event.occurred_at:%Y%m%d_%H%M%S}_{event.event_type.value.lower()}"
            f"_t{track}_{event.event_id[-6:]}.jpg"
        )
        path = self._dir / name
        cv2.imwrite(str(path), evidence)
        return str(path)


class EventLogWriter:
    """One JSON object per line (events.jsonl), line-buffered so it can be tailed live."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("w", encoding="utf-8", buffering=1)

    def write(self, record: dict[str, Any]) -> None:
        self._file.write(json.dumps(record, default=str) + "\n")

    def close(self) -> None:
        self._file.close()
