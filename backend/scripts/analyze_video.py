"""Analyse a video file or live camera: detect, track and count objects, detect line
crossings and zone entries, raise alerts and send SMS.

Run from the `backend` folder:

    python -m scripts.analyze_video                    # sample video
    python -m scripts.analyze_video --show             # with a preview window
    python -m scripts.analyze_video --source my.mp4
    python -m scripts.analyze_video --source "rtsp://user:pass@192.168.1.20:554/stream"
    python -m scripts.analyze_video --source 0         # webcam
    python -m scripts.analyze_video --dry-run          # print SMS instead of sending
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.notifications.manager import NotificationRecord, NotificationStatus
from app.schemas.scene import SceneConfig, load_scene_config
from app.services.video_analysis import AnalysisOptions, AnalysisSession, build_analysis
from app.video.pipeline import RunStatus, RunSummary
from scripts.common import DEFAULT_OUTPUT, DEFAULT_SCENE, DEFAULT_VIDEO, ensure_sample_video

logger = logging.getLogger("analyze_video")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI video analysis with SMS alerts")
    parser.add_argument("--source", default=str(DEFAULT_VIDEO),
                        help="video file, RTSP/HTTP camera URL, or webcam index")
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE,
                        help="scene config: camera, zones, lines, alert rules")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="output folder")
    parser.add_argument("--show", action="store_true", help="show a live preview window")
    parser.add_argument("--no-video", action="store_true", help="don't write annotated.mp4")
    parser.add_argument("--dry-run", action="store_true",
                        help="print SMS to the console instead of sending them")
    parser.add_argument("--max-seconds", type=float, default=None,
                        help="stop after this many seconds of video")
    return parser.parse_args(argv)


def _write_summary(
    session: AnalysisSession, summary: RunSummary, scene: SceneConfig,
    records: list[NotificationRecord],
) -> None:
    payload = summary.to_dict() | {
        "model": session.model_version,
        "camera": scene.camera.model_dump(),
        "notifications": [r.to_dict() for r in records],
    }
    (session.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


def _print_report(
    summary: RunSummary, scene: SceneConfig, records: list[NotificationRecord], output: Path
) -> None:
    rule = "=" * 72
    unique, peak = summary.unique_counts, summary.peak_counts
    camera = scene.camera
    out = [
        "",
        rule,
        f" AI Video Analysis - {summary.source}   [{summary.status.value}]",
        rule,
        f" Camera      : {camera.name}" + (f"  ({camera.location})" if camera.location else ""),
        f" Frames      : {summary.frames_read} read, {summary.frames_processed} analysed"
        f"  |  video {summary.stream_seconds:.1f}s  |  took {summary.processing_seconds:.1f}s",
        "",
        f" PEOPLE      : {unique.get('person', 0)} different people"
        f"  (max {peak.get('person', 0)} at the same time)",
    ]
    if summary.error:
        out.insert(3, f" ERROR       : {summary.error}")

    others = sorted((cls for cls in unique if cls != "person"), key=lambda c: -unique[c])
    if others:
        out.append(" OBJECTS     :")
        out += [f"   - {cls:<12} {unique[cls]:>3} detected  (max {peak.get(cls, 0)} at once)"
                for cls in others]
    else:
        out.append(" OBJECTS     : none besides people")
    for name, counts in summary.line_counts.items():
        out.append(f" LINE        : {name} - IN {counts['in']}, OUT {counts['out']}")
    for name, counts in summary.zone_counts.items():
        out.append(f" ZONE        : {name} - {counts['entries']} entries, {counts['exits']} exits")
    if summary.events_by_type:
        events = ", ".join(f"{k} {v}" for k, v in summary.events_by_type.items())
        out.append(f" EVENTS      : {events}")

    out.append(f" ALERTS      : {len(summary.alerts)}")
    for alert in summary.alerts:
        track = f" track #{alert.event.track_id}" if alert.event.track_id is not None else ""
        repeats = (f"  (+{alert.occurrence_count - 1} repeats suppressed)"
                   if alert.occurrence_count > 1 else "")
        out.append(
            f"   - [{alert.severity.value}] {alert.created_at:%H:%M:%S} @ video "
            f"{alert.stream_time_s:5.1f}s  {alert.event.title}{track}{repeats}"
        )

    sent = [r for r in records if r.status is NotificationStatus.SENT]
    failed = [r for r in records if r.status is NotificationStatus.FAILED]
    rate_limited = len(records) - len(sent) - len(failed)
    out.append(f" SMS         : {len(sent)} sent, {len(failed)} failed, "
               f"{rate_limited} rate-limited")
    for record in sent[:5]:
        note = " (console: printed, not delivered)" if record.provider == "console" else ""
        out.append(f"   - {record.to_masked} via {record.provider}{note}")
    for record in failed:
        out.append(f"   - FAILED {record.to_masked} via {record.provider}: {record.error}")

    out += ["", f" Output      : {output}"]
    if summary.annotated_video:
        out.append(f"   annotated video : {summary.annotated_video.name}")
    out += ["   events log      : events.jsonl", "   snapshots       : snapshots/",
            "   summary         : summary.json", rule, ""]
    print("\n".join(out))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    try:
        scene = load_scene_config(args.scene)
        ensure_sample_video(args.source)
        session = build_analysis(
            settings,
            scene,
            AnalysisOptions(
                source=args.source,
                output_root=args.output,
                show=args.show,
                save_video=not args.no_video,
                dry_run=args.dry_run,
                max_seconds=args.max_seconds,
            ),
        )
    except Exception as exc:
        logger.error("Could not start analysis: %s", exc)
        return 2

    # Ctrl+C stops cleanly: outputs are finalised and pending SMS still go out.
    signal.signal(signal.SIGINT, lambda *_: session.pipeline.stop())
    try:
        summary = session.pipeline.run()
    finally:
        session.close()

    records = session.notifier.records
    _write_summary(session, summary, scene, records)
    _print_report(summary, scene, records, session.output_dir)
    return 1 if summary.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
