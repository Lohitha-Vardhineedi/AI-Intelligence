"""The job runner, with the scripted detector from the pipeline test in place of YOLO."""

from __future__ import annotations

from datetime import UTC

import pytest

from app.ai.tracker import ByteTrackTracker
from app.events.detector import EventDetector
from app.events.processor import EventProcessor
from app.events.rules import RuleEngine
from app.models import EventRecord, JobStatus, Video, VideoProcessingJob
from app.notifications.manager import NotificationManager
from app.services import video_jobs
from app.services.video_analysis import AnalysisSession
from app.video.annotator import FrameAnnotator
from app.video.pipeline import PipelineProgress, VideoPipeline
from app.video.writer import AnnotatedVideoWriter, EventLogWriter, SnapshotStore
from tests.helpers import FakeSMSProvider, scene
from tests.integration.test_pipeline import ScriptedDetector, ScriptedSource


def _scripted_analysis(settings, _scene, options) -> AnalysisSession:
    config = scene()
    output_dir = options.output_root / "run"
    output_dir.mkdir(parents=True)
    notifier = NotificationManager(FakeSMSProvider(), ["9876543210"], sleep=lambda _: None)
    source = ScriptedSource(frames=40)
    pipeline = VideoPipeline(
        source=source,
        detector=ScriptedDetector(),
        tracker=ByteTrackTracker(frame_rate=10),
        event_detector=EventDetector(config, UTC),
        event_processor=EventProcessor(
            rule_engine=RuleEngine(config.rules, UTC), camera=config.camera, tz=UTC,
            notifier=notifier, snapshots=SnapshotStore(output_dir / "snapshots"),
        ),
        annotator=FrameAnnotator(config, UTC),
        video_writer=AnnotatedVideoWriter(output_dir / "annotated.mp4", 10, (1000, 1000)),
        event_log=EventLogWriter(output_dir / "events.jsonl"),
        on_progress=options.on_progress,
    )
    return AnalysisSession(pipeline, source, notifier, output_dir, "scripted")


@pytest.fixture
def queued_job(sync_sessions, storage, sample_video, monkeypatch) -> str:
    monkeypatch.setattr(video_jobs, "sync_session_factory", lambda: sync_sessions)
    monkeypatch.setattr(video_jobs, "get_storage", lambda: storage)
    with sync_sessions() as db:
        video = Video(filename="clip.avi", storage_key="videos/v1/original.avi", size_bytes=1,
                      format="avi", duration_seconds=4, fps=10, width=1000, height=1000,
                      frame_count=40)
        job = VideoProcessingJob(video=video)
        db.add(job)
        db.commit()
        return job.id


def test_completed_job_stores_summary_events_and_outputs(
    client, queued_job, sync_sessions, monkeypatch
):
    monkeypatch.setattr(video_jobs, "build_analysis", _scripted_analysis)

    video_jobs.run_video_job(queued_job)

    with sync_sessions() as db:
        job = db.get(VideoProcessingJob, queued_job)
        events = db.query(EventRecord).filter_by(job_id=queued_job).all()
    assert job.status is JobStatus.COMPLETED
    assert job.progress_percent == 100
    assert job.summary["unique_counts"] == {"car": 1, "person": 2}
    assert len(job.summary["alerts"]) == 1
    assert "snapshot_path" not in job.summary["alerts"][0]
    assert job.annotated_video_key.endswith("annotated.mp4")

    intrusions = [e for e in events if e.event_type == "INTRUSION_DETECTED"]
    assert len(intrusions) == 1
    assert intrusions[0].snapshot_key is not None

    listed = client.get("/api/v1/events", params={"job_id": queued_job,
                                                  "event_type": "INTRUSION_DETECTED"})
    event = listed.json()["data"][0]
    assert event["has_snapshot"] is True
    snapshot = client.get(f"/api/v1/events/{event['id']}/snapshot")
    assert snapshot.headers["content-type"] == "image/jpeg"


def test_job_that_cannot_start_is_marked_failed(queued_job, sync_sessions, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("model file is corrupt")

    monkeypatch.setattr(video_jobs, "build_analysis", broken)

    video_jobs.run_video_job(queued_job)

    with sync_sessions() as db:
        job = db.get(VideoProcessingJob, queued_job)
    assert job.status is JobStatus.FAILED
    assert "model file is corrupt" in job.error_message


def test_progress_is_saved_and_a_cancel_request_stops_the_pipeline(queued_job, sync_sessions):
    class FakePipeline:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    reporter = video_jobs._ProgressReporter(queued_job)
    reporter.pipeline = pipeline = FakePipeline()
    progress = PipelineProgress(frames_read=10, total_frames=40, processing_fps=5.0,
                                elapsed_s=2.0, people_now=1)

    reporter(progress)
    assert not pipeline.stopped
    with sync_sessions() as db:
        job = db.get(VideoProcessingJob, queued_job)
        assert job.progress_percent == 25
        job.cancel_requested = True
        db.commit()

    reporter(progress)
    assert pipeline.stopped


def test_videos_whose_files_are_gone_are_forgotten(queued_job, sync_sessions):
    # The fixture's video has no file in storage, as after a restart on a temporary disk.
    assert video_jobs.forget_missing_videos() == 1

    with sync_sessions() as db:
        assert db.get(VideoProcessingJob, queued_job) is None
