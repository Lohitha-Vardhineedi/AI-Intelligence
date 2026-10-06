"""Video processing pipeline (§9, §62):

source -> sampling -> privacy masks -> detection -> tracking -> event detection
       -> rules / alerts / notifications -> annotation -> outputs
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2

from app.ai.detector import DetectionModel
from app.ai.tracker import ObjectTracker
from app.events.detector import EventDetector, FrameAnalysis
from app.events.geometry import Point
from app.events.processor import EventProcessor
from app.events.types import Alert, Event, EventType
from app.video.annotator import FrameAnnotator
from app.video.processor import FrameSampler, apply_privacy_masks
from app.video.sources import VideoSource
from app.video.writer import AnnotatedVideoWriter, EventLogWriter

logger = logging.getLogger(__name__)

_WINDOW = "AI Video Intelligence  (press Q to quit)"


@dataclass(slots=True)
class PipelineProgress:
    frames_read: int
    frames_processed: int
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
    status: str = "COMPLETED"
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
    output_dir: Path | None = None
    annotated_video: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "is_live": self.is_live,
            "status": self.status,
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
        sampler: FrameSampler,
        privacy_masks: Sequence[Sequence[Point]] = (),
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
        self._sampler = sampler
        self._masks = privacy_masks
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
        self._stop.set()

    def run(self) -> RunSummary:
        source = self._source
        summary = RunSummary(source=source.name, is_live=source.is_live)
        started = time.monotonic()
        last_progress = started
        was_online = True
        people_now = 0

        if not source.is_live:
            self._emit_system(EventType.PROCESSING_STARTED, 0.0, 0, {"source": source.name})
        try:
            while not self._stop.is_set():
                frame = source.read(timeout_s=1.0)
                if source.is_live and source.online != was_online:
                    was_online = source.online
                    kind = EventType.CAMERA_ONLINE if was_online else EventType.CAMERA_OFFLINE
                    self._emit_system(kind, summary.stream_seconds, summary.frames_read, {})
                if frame is None:
                    if source.is_live:
                        continue
                    break  # end of file

                summary.frames_read += 1
                summary.stream_seconds = frame.timestamp_s
                if self._max_seconds is not None and frame.timestamp_s >= self._max_seconds:
                    break
                if not self._sampler.should_process(frame):
                    continue

                frame.image = apply_privacy_masks(frame.image, self._masks)
                detections = self._detector.detect(frame.image)
                tracked = self._tracker.update(detections)
                analysis = self._events.process(frame, tracked)
                self._handle_events(analysis)
                summary.frames_processed += 1
                if analysis.snapshot is not None:
                    people_now = analysis.snapshot.current_counts.get("person", 0)
                self._render(analysis)

                now = time.monotonic()
                if self._on_progress and now - last_progress >= self._progress_interval_s:
                    last_progress = now
                    elapsed = now - started
                    self._on_progress(PipelineProgress(
                        frames_read=summary.frames_read,
                        frames_processed=summary.frames_processed,
                        total_frames=source.frame_count,
                        processing_fps=summary.frames_processed / max(elapsed, 1e-6),
                        elapsed_s=elapsed,
                        people_now=people_now,
                    ))
        except Exception as exc:
            summary.status, summary.error = "FAILED", f"{type(exc).__name__}: {exc}"
            logger.exception("Processing failed")
            if not source.is_live:
                self._emit_system(EventType.PROCESSING_FAILED, summary.stream_seconds,
                                  summary.frames_read, {"error": summary.error})
        else:
            if self._stop.is_set():
                summary.status = "CANCELLED" if not source.is_live else "STOPPED"
            elif not source.is_live:
                self._emit_system(EventType.PROCESSING_COMPLETED, summary.stream_seconds,
                                  summary.frames_read, {"frames": summary.frames_read})
        finally:
            self._close_outputs()

        summary.processing_seconds = time.monotonic() - started
        self._fill_summary(summary)
        return summary

    def _handle_events(self, analysis: FrameAnalysis) -> None:
        for event in analysis.events:
            self._processor.handle(event, analysis.frame.image)
            self._log_event(event)

    def _emit_system(
        self, event_type: EventType, stream_time_s: float, frame_index: int,
        details: dict[str, Any],
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
        if event.event_type not in (EventType.PERSON_DETECTED, EventType.OBJECT_DETECTED):
            logger.info(
                "%s: %s", event.event_type.value, event.title,
                extra={k: v for k, v in (("track", event.track_id), ("zone", event.zone_name),
                                          ("t", f"{event.stream_time_s:.1f}s")) if v is not None},
            )

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
