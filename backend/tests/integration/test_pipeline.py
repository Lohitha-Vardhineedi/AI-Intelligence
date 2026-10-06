"""End-to-end: video -> detection -> tracking -> events -> rule -> alert -> SMS,
with a scripted detector in place of YOLO (fast and deterministic)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC

import numpy as np

from app.ai.tracker import ByteTrackTracker
from app.ai.types import Detection, Frame
from app.events.detector import EventDetector
from app.events.processor import EventProcessor
from app.events.rules import RuleEngine
from app.events.types import EventType
from app.notifications.manager import NotificationManager
from app.video.annotator import FrameAnnotator
from app.video.pipeline import VideoPipeline
from app.video.processor import FrameSampler
from app.video.sources import VideoSource
from app.video.writer import AnnotatedVideoWriter, EventLogWriter, SnapshotStore
from tests.helpers import FakeSMSProvider, detection, make_frame, scene


class ScriptedSource(VideoSource):
    def __init__(self, frames: int) -> None:
        super().__init__(UTC)
        self.fps, self.width, self.height, self.frame_count = 10.0, 1000, 1000, frames
        self._i = 0

    @property
    def name(self) -> str:
        return "scripted.mp4"

    def open(self) -> None: ...

    def read(self, timeout_s: float = 1.0) -> Frame | None:
        if self._i >= self.frame_count:
            return None
        frame = make_frame(self._i)
        self._i += 1
        return frame

    def close(self) -> None: ...


class ScriptedDetector:
    """Two people: one walks into the room, one stays outside. Plus a parked car."""

    class_names: Mapping[int, str] = {0: "person", 2: "car"}
    model_version = "scripted"

    def __init__(self) -> None:
        self._frame = 0

    def detect(self, frame: np.ndarray) -> list[Detection]:
        i = self._frame
        self._frame += 1
        return [
            detection(0.20 + i * 0.02, 0.5),  # walks right, into the room
            detection(0.15, 0.80 - i * 0.002),  # stays on the left
            detection(0.10, 0.20, cls="car", class_id=2),
        ]


def test_full_pipeline_sends_one_sms_for_room_entry(tmp_path):
    config = scene()
    provider = FakeSMSProvider()
    notifier = NotificationManager(provider, ["9381558756"], sleep=lambda _: None)
    processor = EventProcessor(
        rule_engine=RuleEngine(config.rules, UTC), camera=config.camera, tz=UTC,
        notifier=notifier, snapshots=SnapshotStore(tmp_path / "snapshots"),
    )
    source = ScriptedSource(frames=40)
    pipeline = VideoPipeline(
        source=source,
        detector=ScriptedDetector(),
        tracker=ByteTrackTracker(frame_rate=10),
        event_detector=EventDetector(config, UTC),
        event_processor=processor,
        sampler=FrameSampler(10, is_live=False, inference_fps=10),
        annotator=FrameAnnotator(config, UTC),
        video_writer=AnnotatedVideoWriter(tmp_path / "annotated.mp4", 10, (1000, 1000)),
        event_log=EventLogWriter(tmp_path / "events.jsonl"),
    )

    summary = pipeline.run()
    notifier.close(wait=True)

    assert summary.status == "COMPLETED"
    assert summary.frames_processed == 40
    assert summary.unique_counts == {"car": 1, "person": 2}
    assert summary.line_counts["Door"] == {"in": 1, "out": 0}
    assert summary.events_by_type[EventType.INTRUSION_DETECTED.value] == 1
    assert len(summary.alerts) == 1
    assert summary.alerts[0].event.snapshot_path is not None
    assert len(provider.sent) == 1
    assert provider.sent[0][0] == "+919381558756"
    assert (tmp_path / "annotated.mp4").stat().st_size > 0
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) >= 5
