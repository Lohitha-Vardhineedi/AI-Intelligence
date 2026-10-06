"""Builds a ready-to-run analysis pipeline from settings + scene configuration.

This is the single place where concrete implementations are chosen (dependency
injection). The CLI uses it today; the Celery worker and stream service will reuse it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.ai.classes import expand_classes
from app.ai.model_manager import load_detection_model
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
from app.video.processor import FrameSampler
from app.video.sources import VideoSource, create_video_source
from app.video.writer import AnnotatedVideoWriter, EventLogWriter, SnapshotStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AnalysisOptions:
    source: str
    output_root: Path
    show: bool = False
    save_video: bool = True
    dry_run: bool = False  # print SMS to the console instead of sending
    max_seconds: float | None = None


@dataclass(slots=True)
class AnalysisSession:
    pipeline: VideoPipeline
    source: VideoSource
    notifier: NotificationManager
    output_dir: Path
    model_version: str

    def close(self) -> None:
        self.notifier.close(wait=True)
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
    if any(r.enabled and r.actions.sms and not r.recipients for r in scene.rules) and not (
        notifier.default_recipients
    ):
        logger.warning("SMS rules are configured but SMS_RECIPIENTS is empty in .env")

    source = create_video_source(options.source, tz)
    source.open()
    try:
        detection = scene.detection
        confidence = detection.confidence_threshold or settings.ai_confidence_threshold
        detector = load_detection_model(
            settings,
            classes=expand_classes(detection.classes) or None,
            # ByteTrack needs the low-confidence detections too (see Settings).
            confidence_threshold=min(confidence, settings.ai_tracker_low_threshold),
            iou_threshold=detection.iou_threshold or settings.ai_iou_threshold,
        )
        sampler = FrameSampler(
            source.fps,
            is_live=source.is_live,
            inference_fps=detection.inference_fps,
            frame_skip=detection.frame_skip,
        )
        tracker = ByteTrackTracker(
            frame_rate=sampler.effective_fps,
            high_threshold=confidence,
            low_threshold=settings.ai_tracker_low_threshold,
            lost_buffer_seconds=scene.tracking.lost_timeout_seconds,
        )

        output_dir = _output_dir(options.output_root, source)
        processor = EventProcessor(
            rule_engine=RuleEngine(scene.rules, tz),
            camera=scene.camera,
            tz=tz,
            notifier=notifier,
            snapshots=SnapshotStore(output_dir / "snapshots"),
        )
        writer = (
            AnnotatedVideoWriter(
                output_dir / "annotated.mp4", sampler.effective_fps, (source.width, source.height)
            )
            if options.save_video
            else None
        )
        pipeline = VideoPipeline(
            source=source,
            detector=detector,
            tracker=tracker,
            event_detector=EventDetector(scene, tz, confirm_threshold=confidence),
            event_processor=processor,
            sampler=sampler,
            privacy_masks=[m.points for m in scene.privacy_masks],
            annotator=FrameAnnotator(scene, tz) if (options.save_video or options.show) else None,
            video_writer=writer,
            event_log=EventLogWriter(output_dir / "events.jsonl"),
            display=options.show,
            max_seconds=options.max_seconds,
            on_progress=_log_progress,
        )
    except Exception:
        source.close()
        notifier.close(wait=False)
        raise

    logger.info(
        "Analysing %s (%dx%d @ %.1f fps) - inference at %.1f fps, SMS provider: %s",
        source.name, source.width, source.height, source.fps, sampler.effective_fps,
        notifier.provider_name,
    )
    return AnalysisSession(pipeline, source, notifier, output_dir, detector.model_version)
