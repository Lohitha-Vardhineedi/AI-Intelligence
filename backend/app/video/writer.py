"""Run outputs: annotated video, evidence snapshots and the event log."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.events.types import Event

logger = logging.getLogger(__name__)

# Browsers play H.264. pip builds of OpenCV can't encode it, so the writer uses the ffmpeg
# command when it is installed (Linux servers, the Docker image). Otherwise it uses
# Windows' built-in encoder (Media Foundation), then MPEG-4 Part 2 as a last resort.
_OPENCV_BACKENDS = (
    ((cv2.CAP_MSMF, "avc1"),) if sys.platform == "win32" else ()
) + ((cv2.CAP_FFMPEG, "avc1"), (cv2.CAP_FFMPEG, "mp4v"))


class AnnotatedVideoWriter:
    def __init__(self, path: Path, fps: float, size: tuple[int, int], *, threads: int = 0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._writer: cv2.VideoWriter | None = None
        if ffmpeg := shutil.which("ffmpeg"):
            self._ffmpeg = _start_ffmpeg(ffmpeg, path, fps, size, threads)
            logger.info("Writing annotated video %s (ffmpeg, H.264)", path.name)
            return
        for backend, codec in _OPENCV_BACKENDS:
            writer = cv2.VideoWriter(str(path), backend, cv2.VideoWriter_fourcc(*codec), fps, size)
            if writer.isOpened():
                self._writer = writer
                logger.info("Writing annotated video %s (codec %s)", path.name, codec)
                return
            writer.release()
        raise RuntimeError(f"Could not create a video writer for {path}")

    def write(self, image: np.ndarray) -> None:
        if self._ffmpeg is not None and self._ffmpeg.stdin is not None:
            try:
                self._ffmpeg.stdin.write(np.ascontiguousarray(image).data)
            except BrokenPipeError as exc:
                raise RuntimeError(f"ffmpeg stopped: {self._ffmpeg_errors()}") from exc
        elif self._writer is not None:
            self._writer.write(image)

    def close(self) -> None:
        if self._ffmpeg is not None:
            if self._ffmpeg.stdin is not None:
                self._ffmpeg.stdin.close()
            if self._ffmpeg.wait(timeout=120) != 0:
                logger.error("ffmpeg failed: %s", self._ffmpeg_errors())
            self._ffmpeg = None
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    def _ffmpeg_errors(self) -> str:
        if self._ffmpeg is None or self._ffmpeg.stderr is None:
            return ""
        return self._ffmpeg.stderr.read().decode(errors="replace").strip()[-500:]


def _start_ffmpeg(
    ffmpeg: str, path: Path, fps: float, size: tuple[int, int], threads: int
) -> subprocess.Popen[bytes]:
    width, height = size
    command = [
        ffmpeg, "-loglevel", "error", "-y",
        # Input: raw BGR frames on stdin, exactly as OpenCV holds them.
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:g}",
        "-i", "-",
        # Output: H.264 MP4 that starts playing before it has fully downloaded.
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",  # yuv420p needs even dimensions
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if threads:
        command += ["-threads", str(threads)]
    command.append(str(path))
    return subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


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
