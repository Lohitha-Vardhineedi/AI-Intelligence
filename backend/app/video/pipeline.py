"""source -> privacy mask -> detection -> tracking -> scene events -> rules, alerts, SMS
-> annotation -> outputs"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import cv2

from app.ai.detector import DetectionModel
from app.ai.tracker import ObjectTracker
from app.ai.types import Frame
from app.events.detector import EventDetector, FrameAnalysis
from app.events.processor import EventProcessor
from app.events.types import Alert, Event, EventType
from app.video.annotator import FrameAnnotator
from app.video.privacy import PrivacyMask
from app.video.sources import VideoSource
from app.video.writer import AnnotatedVideoWriter, EventLogWriter

logger = logging.getLogger(__name__)

_WINDOW = "AI Video Intelligence  (press Q to quit)"
_QUIET_EVENTS = frozenset({EventType.PERSON_DETECTED, EventType.OBJECT_DETECTED})


class RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"  # a file run stopped early
    STOPPED = "STOPPED"  # a live run stopped


@dataclass(slots=True)
class PipelineProgress:
    frames_read: int
    total_frames: int | None
    processing_fps: float
    elapsed_s: float
    people_now: int

    @property
    def percent(self) -> float | None:
        if not self.total_frames:
            return None
        return min(100.0, 100.0 * self.frames_read / self.total_frames)

    @property
    def eta_s(self) -> float | None:
        if not self.total_frames or self.frames_read == 0:
            return None
        rate = self.frames_read / max(self.elapsed_s, 1e-6)
        return max(0.0, (self.total_frames - self.frames_read) / rate)


@dataclass(slots=True)
class RunSummary:
    source: str
    is_live: bool
    status: RunStatus = RunStatus.COMPLETED
    error: str | None = None
    frames_read: int = 0
    frames_processed: int = 0
    stream_seconds: float = 0.0
    processing_seconds: float = 0.0
    unique_counts: dict[str, int] = field(default_factory=dict)
    peak_counts: dict[str, int] = field(default_factory=dict)
    line_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    zone_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    events_by_type: dict[str, int] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
    annotated_video: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "is_live": self.is_live,
            "status": self.status.value,
            "error": self.error,
            "frames_read": self.frames_read,
            "frames_processed": self.frames_processed,
            "stream_seconds": round(self.stream_seconds, 2),
            "processing_seconds": round(self.processing_seconds, 2),
            "unique_counts": self.unique_counts,
            "peak_counts": self.peak_counts,
            "line_counts": self.line_counts,
            "zone_counts": self.zone_counts,
            "events_by_type": self.events_by_type,
            "alerts": [a.to_dict() for a in self.alerts],
            "annotated_video": str(self.annotated_video) if self.annotated_video else None,
        }


class VideoPipeline:
    def __init__(
        self,
        *,
        source: VideoSource,
        detector: DetectionModel,
        tracker: ObjectTracker,
        event_detector: EventDetector,
        event_processor: EventProcessor,
        privacy_mask: PrivacyMask | None = None,
        annotator: FrameAnnotator | None = None,
        video_writer: AnnotatedVideoWriter | None = None,
        event_log: EventLogWriter | None = None,
        display: bool = False,
        max_seconds: float | None = None,
        on_progress: Callable[[PipelineProgress], None] | None = None,
        progress_interval_s: float = 2.0,
    ) -> None:
        self._source = source
        self._detector = detector
        self._tracker = tracker
        self._events = event_detector
        self._processor = event_processor
        self._privacy_mask = privacy_mask
        self._annotator = annotator
        self._writer = video_writer
        self._event_log = event_log
        self._display = display
        self._max_seconds = max_seconds
        self._on_progress = on_progress
        self._progress_interval_s = progress_interval_s
        self._stop = threading.Event()
        self._event_counts: Counter[str] = Counter()

    def stop(self) -> None:
        """Thread-safe; the run finishes the current frame and closes its outputs."""
        self._stop.set()

    def run(self) -> RunSummary:
        source = self._source
        summary = RunSummary(source=source.name, is_live=source.is_live)
        started = last_progress = time.monotonic()
        was_online = True

        if not source.is_live:
            self._emit_system(EventType.PROCESSING_STARTED, details={"source": source.name})
        try:
            while not self._stop.is_set():
                frame = source.read(timeout_s=1.0)
                if source.is_live and source.online != was_online:
                    was_online = source.online
                    self._emit_system(
                        EventType.CAMERA_ONLINE if was_online else EventType.CAMERA_OFFLINE,
                        stream_time_s=summary.stream_seconds,
                        frame_index=source.frames_read,
                    )
                if frame is None:
                    if source.is_live:
                        continue
                    break  # end of file

                summary.stream_seconds = frame.timestamp_s
                if self._max_seconds is not None and frame.timestamp_s >= self._max_seconds:
                    break
                analysis = self._process(frame)
                summary.frames_processed += 1

                now = time.monotonic()
                if self._on_progress and now - last_progress >= self._progress_interval_s:
                    last_progress = now
                    self._on_progress(PipelineProgress(
                        frames_read=source.frames_read,
                        total_frames=source.frame_count,
                        processing_fps=summary.frames_processed / (now - started),
                        elapsed_s=now - started,
                        people_now=analysis.snapshot.current_counts["person"],
                    ))
        except Exception as exc:
            summary.status, summary.error = RunStatus.FAILED, f"{type(exc).__name__}: {exc}"
            logger.exception("Processing failed")
            if not source.is_live:
                self._emit_system(EventType.PROCESSING_FAILED,
                                  stream_time_s=summary.stream_seconds,
                                  frame_index=source.frames_read,
                                  details={"error": summary.error})
        else:
            if self._stop.is_set():
                summary.status = RunStatus.STOPPED if source.is_live else RunStatus.CANCELLED
            elif not source.is_live:
                self._emit_system(EventType.PROCESSING_COMPLETED,
                                  stream_time_s=summary.stream_seconds,
                                  frame_index=source.frames_read,
                                  details={"frames": source.frames_read})
        finally:
            self._close_outputs()

        summary.frames_read = source.frames_read
        summary.processing_seconds = time.monotonic() - started
        self._fill_summary(summary)
        return summary

    def _process(self, frame: Frame) -> FrameAnalysis:
        if self._privacy_mask is not None:
            self._privacy_mask.apply(frame.image)
        tracked = self._tracker.update(self._detector.detect(frame.image))
        analysis = self._events.process(frame, tracked)
        for event in analysis.events:
            self._processor.handle(event, frame.image)
            self._log_event(event)
        self._render(analysis)
        return analysis

    def _emit_system(
        self,
        event_type: EventType,
        *,
        stream_time_s: float = 0.0,
        frame_index: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = self._events.factory.system(
            event_type, stream_time_s=stream_time_s, frame_index=frame_index, details=details
        )
        self._processor.handle(event)
        self._log_event(event)

    def _log_event(self, event: Event) -> None:
        self._event_counts[event.event_type.value] += 1
        if self._event_log is not None:
            self._event_log.write(event.to_dict())
        if event.event_type not in _QUIET_EVENTS:
            extra = {"track": event.track_id, "zone": event.zone_name,
                     "t": f"{event.stream_time_s:.1f}s"}
            logger.info("%s: %s", event.event_type.value, event.title,
                        extra={k: v for k, v in extra.items() if v is not None})

    def _render(self, analysis: FrameAnalysis) -> None:
        if self._annotator is None or (self._writer is None and not self._display):
            return
        annotated = self._annotator.draw(analysis.frame.image, analysis, self._processor.alerts)
        if self._writer is not None:
            self._writer.write(annotated)
        if self._display:
            try:
                cv2.imshow(_WINDOW, annotated)
                if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                    self.stop()
            except cv2.error:
                logger.warning("Cannot open a display window here; continuing without --show")
                self._display = False

    def _close_outputs(self) -> None:
        if self._writer is not None:
            self._writer.close()
        if self._event_log is not None:
            self._event_log.close()
        if self._display:
            cv2.destroyAllWindows()

    def _fill_summary(self, summary: RunSummary) -> None:
        events = self._events
        summary.unique_counts = events.counter.unique
        summary.peak_counts = dict(events.counter.peak.most_common())
        summary.line_counts = {
            ln.line.name: {"in": ln.in_count, "out": ln.out_count} for ln in events.lines
        }
        summary.zone_counts = {
            z.zone.name: {"entries": z.entries, "exits": z.exits} for z in events.zones
        }
        summary.events_by_type = dict(self._event_counts.most_common())
        summary.alerts = list(self._processor.alerts)
        if self._writer is not None:
            summary.annotated_video = self._writer.path
