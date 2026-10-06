"""Video sources: files, RTSP/HTTP cameras and webcams.

Sources also do the frame sampling, because that is where it is cheapest: a file source
skips frames with grab() (no colour conversion or copy), and a camera source hands out
only the newest frame, at most `inference_fps` times a second.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path

import cv2

from app.ai.types import Frame

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv"})
STREAM_SCHEMES = ("rtsp://", "rtsps://", "http://", "https://")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")


class VideoSourceError(RuntimeError):
    pass


def redact_url(url: str) -> str:
    """'rtsp://admin:secret@10.0.0.5/stream' -> 'rtsp://***@10.0.0.5/stream'."""
    return _URL_CREDENTIALS.sub(r"\g<scheme>***@", url)


@dataclass(frozen=True, slots=True)
class VideoInfo:
    fps: float
    width: int
    height: int
    frame_count: int  # 0 if the container doesn't say

    @property
    def duration_s(self) -> float:
        return self.frame_count / self.fps if self.fps > 0 else 0.0


def probe_video(path: Path) -> VideoInfo:
    """Basic properties of a video file. Raises VideoSourceError if it can't be decoded."""
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened() or not capture.read()[0]:
            raise VideoSourceError("The file could not be decoded as a video")
        return VideoInfo(
            fps=capture.get(cv2.CAP_PROP_FPS) or 25.0,
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            frame_count=max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT))),
        )
    finally:
        capture.release()


def frame_step(source_fps: float, inference_fps: float | None, frame_skip: int | None) -> int:
    """Source frames to advance per analysed frame."""
    if frame_skip is not None:
        return frame_skip + 1
    if inference_fps and source_fps > inference_fps:
        return max(1, round(source_fps / inference_fps))
    return 1


class VideoSource(ABC):
    is_live = False

    def __init__(self, tz: tzinfo) -> None:
        self._tz = tz
        self.fps = 25.0
        self.effective_fps = 25.0  # rate at which read() hands out frames
        self.width = 0
        self.height = 0
        self.frame_count: int | None = None  # unknown for live streams
        self.frames_read = 0  # frames taken from the source, skipped ones included

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def online(self) -> bool:
        return True

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def read(self, timeout_s: float = 1.0) -> Frame | None:
        """Next frame to analyse. None at the end of a file, or if a live source has no new
        frame within `timeout_s`."""

    @abstractmethod
    def close(self) -> None: ...


class FileVideoSource(VideoSource):
    def __init__(
        self,
        path: Path,
        tz: tzinfo,
        *,
        inference_fps: float | None = None,
        frame_skip: int | None = None,
    ) -> None:
        super().__init__(tz)
        self.path = path
        self._inference_fps = inference_fps
        self._frame_skip = frame_skip
        self._step = 1
        self._capture: cv2.VideoCapture | None = None

    @property
    def name(self) -> str:
        return self.path.name

    def open(self) -> None:
        if not self.path.is_file():
            raise VideoSourceError(f"Video file not found: {self.path}")
        if self.path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise VideoSourceError(
                f"Unsupported format '{self.path.suffix}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}"
            )
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            raise VideoSourceError(f"Could not open video: {self.path.name}")
        self._capture = capture
        self.fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        self._step = frame_step(self.fps, self._inference_fps, self._frame_skip)
        self.effective_fps = self.fps / self._step
        self.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frame_count = count if count > 0 else None

    def read(self, timeout_s: float = 1.0) -> Frame | None:
        if self._capture is None:
            raise VideoSourceError("Source is not open")
        if self.frames_read:
            for _ in range(self._step - 1):
                if not self._capture.grab():
                    return None
                self.frames_read += 1
        ok, image = self._capture.read()
        if not ok:
            return None
        index = self.frames_read
        self.frames_read += 1
        return Frame(
            image=image,
            index=index,
            timestamp_s=index / self.fps,
            captured_at=datetime.now(self._tz),
        )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class StreamVideoSource(VideoSource):
    """RTSP/HTTP camera or local webcam.

    A background thread reads continuously and keeps only the newest frame, so analysis
    never falls behind real time. A dropped connection is retried with exponential backoff.
    """

    is_live = True

    def __init__(
        self,
        url: str | int,
        tz: tzinfo,
        *,
        inference_fps: float | None = None,
        connect_timeout_s: float = 10.0,
        offline_after_s: float = 5.0,
        max_backoff_s: float = 30.0,
    ) -> None:
        super().__init__(tz)
        self._url = url
        self._inference_fps = inference_fps
        # 5% slack, so camera timing jitter doesn't make us skip a frame we wanted.
        self._min_interval_s = 0.95 / inference_fps if inference_fps else 0.0
        self._connect_timeout_s = connect_timeout_s
        self._offline_after_s = offline_after_s
        self._max_backoff_s = max_backoff_s
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._returned_index = -1
        self._returned_at_s = -math.inf
        self._started_at = 0.0
        self._last_frame_at = 0.0

    @property
    def name(self) -> str:
        return f"webcam {self._url}" if isinstance(self._url, int) else redact_url(self._url)

    @property
    def online(self) -> bool:
        return time.monotonic() - self._last_frame_at <= self._offline_after_s

    def open(self) -> None:
        if self._thread is not None:
            return
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="video-reader", daemon=True)
        self._thread.start()
        with self._condition:
            connected = self._condition.wait_for(
                lambda: self._latest is not None, timeout=self._connect_timeout_s + 2
            )
        if not connected:
            self.close()
            raise VideoSourceError(f"Unable to connect to camera: {self.name}")

    def read(self, timeout_s: float = 1.0) -> Frame | None:
        with self._condition:
            if not self._condition.wait_for(self._frame_ready, timeout_s) or self._stop.is_set():
                return None
            frame = self._latest
            assert frame is not None
            self._returned_index, self._returned_at_s = frame.index, frame.timestamp_s
            return frame

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _frame_ready(self) -> bool:
        if self._stop.is_set():
            return True
        frame = self._latest
        return (
            frame is not None
            and frame.index != self._returned_index
            and frame.timestamp_s - self._returned_at_s >= self._min_interval_s
        )

    def _connect(self) -> cv2.VideoCapture | None:
        if isinstance(self._url, int):
            capture = cv2.VideoCapture(self._url)
        else:
            # RTSP over TCP is far more reliable than UDP on Wi-Fi and the internet.
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
            timeout_ms = int(self._connect_timeout_s * 1000)
            capture = cv2.VideoCapture(
                self._url,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms,
                 cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_ms],
            )
        if not capture.isOpened():
            capture.release()
            return None
        self.fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        self.effective_fps = min(self.fps, self._inference_fps or self.fps)
        self.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return capture

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            capture = self._connect()
            if capture is None:
                logger.warning("Cannot connect to %s; retrying in %.0fs", self.name, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._max_backoff_s)
                continue
            logger.info("Connected to %s (%dx%d @ %.1f fps)", self.name, self.width,
                        self.height, self.fps)
            backoff = 1.0
            while not self._stop.is_set():
                ok, image = capture.read()
                if not ok:
                    logger.warning("Stream interrupted: %s", self.name)
                    break
                now = time.monotonic()
                with self._condition:
                    self._latest = Frame(
                        image=image,
                        index=self.frames_read,
                        timestamp_s=now - self._started_at,
                        captured_at=datetime.now(self._tz),
                    )
                    self.frames_read += 1
                    self._last_frame_at = now
                    self._condition.notify_all()
            capture.release()


def create_video_source(
    source: str,
    tz: tzinfo,
    *,
    inference_fps: float | None = None,
    frame_skip: int | None = None,
) -> VideoSource:
    """'0' is webcam 0, 'rtsp://...' a camera stream, anything else a video file."""
    if source.isdigit():
        return StreamVideoSource(int(source), tz, inference_fps=inference_fps)
    if source.lower().startswith(STREAM_SCHEMES):
        return StreamVideoSource(source, tz, inference_fps=inference_fps)
    return FileVideoSource(Path(source), tz, inference_fps=inference_fps, frame_skip=frame_skip)
