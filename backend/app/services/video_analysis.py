"""Wires a ready-to-run pipeline from settings and scene config. This is the only place
that picks concrete implementations; everything else depends on interfaces."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2

from app.ai.classes import expand_classes
from app.ai.detector import OnnxDetectionModel, YoloDetectionModel, load_detection_model
from app.ai.tracker import ByteTrackTracker
from app.core.config import Settings
from app.events.detector import EventDetector
from app.events.processor import EventProcessor
from app.events.rules import RuleEngine
from app.notifications.manager import NotificationManager
from app.notifications.providers.console import ConsoleSMSProvider
from app.notifications.sms import create_sms_provider
from app.schemas.scene import SceneConfig
from app.video.annotator import FrameAnnotator
from app.video.pipeline import PipelineProgress, VideoPipeline
from app.video.privacy import PrivacyMask
from app.video.sources import VideoSource, create_video_source
from app.video.writer import AnnotatedVideoWriter, EventLogWriter, SnapshotStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AnalysisOptions:
    source: str
    output_root: Path
    show: bool = False
    save_video: bool = True
    dry_run: bool = False  # print SMS instead of sending them
    max_seconds: float | None = None
    on_progress: Callable[[PipelineProgress], None] | None = None  # default: log it
    progress_interval_s: float = 2.0


@dataclass(slots=True)
class AnalysisSession:
    pipeline: VideoPipeline
    source: VideoSource
    notifier: NotificationManager
    output_dir: Path
    model_version: str

    def close(self) -> None:
        self.notifier.close(wait=True)  # deliver SMS still in flight
        self.source.close()


def _log_progress(progress: PipelineProgress) -> None:
    pct = f"{progress.percent:5.1f}% | " if progress.percent is not None else ""
    eta = f" | ETA {progress.eta_s:.0f}s" if progress.eta_s is not None else ""
    logger.info(
        "Progress %s%d frames | %.1f fps%s | people now: %d",
        pct, progress.frames_read, progress.processing_fps, eta, progress.people_now,
    )


def _output_dir(root: Path, source: VideoSource) -> Path:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(source.name).stem)[:40] or "stream"
    path = root / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_detector(
    settings: Settings, scene: SceneConfig, confidence: float, source: VideoSource
) -> YoloDetectionModel | OnnxDetectionModel:
    if settings.ai_cpu_threads:
        cv2.setNumThreads(settings.ai_cpu_threads)
    detector = load_detection_model(
        settings.resolve_path(settings.ai_model_path),
        device=settings.ai_device,
        # The tracker needs the weak detections too; see Settings.ai_tracker_low_threshold.
        confidence_threshold=min(confidence, settings.ai_tracker_low_threshold),
        iou_threshold=scene.detection.iou_threshold or settings.ai_iou_threshold,
        image_size=settings.ai_image_size,
        classes=expand_classes(scene.detection.classes) or None,
        threads=settings.ai_cpu_threads,
    )
    detector.warm_up(source.width or 640, source.height or 480)
    return detector


def build_analysis(
    settings: Settings, scene: SceneConfig, options: AnalysisOptions
) -> AnalysisSession:
    tz = settings.tz
    provider = ConsoleSMSProvider() if options.dry_run else create_sms_provider(settings)
    notifier = NotificationManager(
        provider,
        settings.recipients,
        default_country_code=settings.sms_default_country_code,
        max_per_hour=settings.sms_max_per_hour,
    )
    sms_rules_need_defaults = any(
        r.enabled and r.actions.sms and not r.recipients for r in scene.rules
    )
    if sms_rules_need_defaults and not notifier.default_recipients:
        logger.warning("SMS rules are configured but SMS_RECIPIENTS is empty in .env")

    source = create_video_source(
        options.source,
        tz,
        inference_fps=settings.ai_inference_fps or scene.detection.inference_fps,
        frame_skip=scene.detection.frame_skip,
    )
    source.open()
    try:
        confidence = scene.detection.confidence_threshold or settings.ai_confidence_threshold
        detector = _load_detector(settings, scene, confidence, source)
        output_dir = _output_dir(options.output_root, source)
        writer = (
            AnnotatedVideoWriter(
                output_dir / "annotated.mp4",
                source.effective_fps,
                (source.width, source.height),
                threads=settings.ai_cpu_threads,
            )
            if options.save_video
            else None
        )
        pipeline = VideoPipeline(
            source=source,
            detector=detector,
            tracker=ByteTrackTracker(
                frame_rate=source.effective_fps,
                high_threshold=confidence,
                low_threshold=settings.ai_tracker_low_threshold,
                lost_buffer_seconds=scene.tracking.lost_timeout_seconds,
            ),
            event_detector=EventDetector(scene, tz, confirm_threshold=confidence),
            event_processor=EventProcessor(
                rule_engine=RuleEngine(scene.rules, tz),
                camera=scene.camera,
                tz=tz,
                notifier=notifier,
                snapshots=SnapshotStore(output_dir / "snapshots"),
            ),
            privacy_mask=PrivacyMask([m.points for m in scene.privacy_masks]),
            annotator=FrameAnnotator(scene, tz) if (options.save_video or options.show) else None,
            video_writer=writer,
            event_log=EventLogWriter(output_dir / "events.jsonl"),
            display=options.show,
            max_seconds=options.max_seconds,
            on_progress=options.on_progress or _log_progress,
            progress_interval_s=options.progress_interval_s,
        )
    except Exception:
        source.close()
        notifier.close(wait=False)
        raise

    logger.info(
        "Analysing %s (%dx%d @ %.1f fps) - inference at %.1f fps, SMS provider: %s",
        source.name, source.width, source.height, source.fps, source.effective_fps,
        notifier.provider_name,
    )
    return AnalysisSession(pipeline, source, notifier, output_dir, detector.model_version)
