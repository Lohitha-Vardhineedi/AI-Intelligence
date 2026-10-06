"""Video sources: uploaded files, RTSP/IP cameras and local webcams (§8).

New source types (ONVIF, WebRTC, NVR) only need to implement `VideoSource`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, tzinfo
from pathlib import Path
from types import TracebackType

import cv2

from app.ai.types import Frame
from app.security.url_guard import is_stream_url, redact_url

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv"})


class VideoSourceError(RuntimeError):
    pass


class VideoSource(ABC):
    is_live: bool = False

    def __init__(self, tz: tzinfo) -> None:
        self._tz = tz
        self.fps: float = 25.0
        self.width = 0
        self.height = 0
        self.frame_count: int | None = None

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
        """Next frame. None means end of file, or no new frame yet for live sources."""

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> VideoSource:
        self.open()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class FileVideoSource(VideoSource):
    """Uploaded video file. Every frame is read in order; nothing is dropped."""

    def __init__(self, path: Path, tz: tzinfo) -> None:
        super().__init__(tz)
        self.path = path
        self._capture: cv2.VideoCapture | None = None
        self._index = 0

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
        self.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frame_count = count if count > 0 else None

    def read(self, timeout_s: float = 1.0) -> Frame | None:
        if self._capture is None:
            raise VideoSourceError("Source is not open")
        ok, image = self._capture.read()
        if not ok:
            return None
        frame = Frame(
            image=image,
            index=self._index,
            timestamp_s=self._index / self.fps,
            captured_at=datetime.now(self._tz),
        )
        self._index += 1
        return frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class StreamVideoSource(VideoSource):
    """Live RTSP / HTTP camera or local webcam.

    A background thread reads continuously and keeps only the latest frame, so analysis
    never falls behind real time. If the connection drops, it reconnects with
    exponential backoff.
    """

    is_live = True

    def __init__(
        self,
        url: str | int,
        tz: tzinfo,
        *,
        connect_timeout_s: float = 10.0,
        offline_after_s: float = 5.0,
        max_backoff_s: float = 30.0,
    ) -> None:
        super().__init__(tz)
        self._url = url
        self._connect_timeout_s = connect_timeout_s
        self._offline_after_s = offline_after_s
        self._max_backoff_s = max_backoff_s
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._sequence = 0
        self._consumed = 0
        self._last_frame_at = 0.0
        self._started_at = 0.0

    @property
    def name(self) -> str:
        return f"webcam {self._url}" if isinstance(self._url, int) else redact_url(self._url)

    @property
    def online(self) -> bool:
        return time.monotonic() - self._last_frame_at <= self._offline_after_s

    def _connect(self) -> cv2.VideoCapture | None:
        if isinstance(self._url, int):
            capture = cv2.VideoCapture(self._url)
        else:
            # TCP is far more reliable than UDP for RTSP over Wi-Fi and the internet.
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
            timeout_ms = int(self._connect_timeout_s * 1000)
            capture = cv2.VideoCapture(
                self._url,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                 timeout_ms],
            )
        if not capture.isOpened():
            capture.release()
            return None
        self.fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
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
                        index=self._sequence,
                        timestamp_s=now - self._started_at,
                        captured_at=datetime.now(self._tz),
                    )
                    self._sequence += 1
                    self._last_frame_at = now
                    self._condition.notify_all()
            capture.release()

    def open(self) -> None:
        if self._thread is not None:
            return
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="video-reader", daemon=True)
        self._thread.start()
        with self._condition:
            got_frame = self._condition.wait_for(
                lambda: self._sequence > 0, timeout=self._connect_timeout_s + 2
            )
        if not got_frame:
            self.close()
            raise VideoSourceError(f"Unable to connect to camera: {self.name}")

    def read(self, timeout_s: float = 1.0) -> Frame | None:
        with self._condition:
            if not self._condition.wait_for(
                lambda: self._sequence != self._consumed or self._stop.is_set(), timeout_s
            ):
                return None
            self._consumed = self._sequence
            return self._latest

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


def create_video_source(source: str, tz: tzinfo) -> VideoSource:
    """'0' -> webcam 0, 'rtsp://...' -> camera stream, anything else -> video file."""
    if source.isdigit():
        return StreamVideoSource(int(source), tz)
    if is_stream_url(source):
        return StreamVideoSource(source, tz)
    return FileVideoSource(Path(source), tz)
