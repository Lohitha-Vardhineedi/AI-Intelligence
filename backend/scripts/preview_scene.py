"""Draw the configured zones and lines on one video frame, to check their coordinates.

    python -m scripts.preview_scene                          # sample video, frame 300
    python -m scripts.preview_scene --source my.mp4 --frame 50

Coordinates in config/scene.yaml are fractions of the frame (x=0 left, x=1 right,
y=0 top, y=1 bottom). The preview adds a 10% grid to help read them.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import cv2

from app.ai.types import Frame
from app.core.config import get_settings
from app.events.detector import FrameAnalysis, SceneSnapshot
from app.schemas.scene import load_scene_config
from app.video.annotator import FrameAnnotator
from scripts.common import DEFAULT_OUTPUT, DEFAULT_SCENE, DEFAULT_VIDEO, ensure_sample_video

_GRID = (180, 180, 180)
_TEXT = (255, 255, 255)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview zones and lines on a frame")
    parser.add_argument("--source", default=str(DEFAULT_VIDEO))
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--frame", type=int, default=300)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "scene_preview.jpg")
    args = parser.parse_args(argv)

    settings = get_settings()
    scene = load_scene_config(args.scene)
    ensure_sample_video(args.source)
    capture = cv2.VideoCapture(int(args.source) if args.source.isdigit() else args.source)
    if not capture.isOpened():
        print(f"Could not open {args.source}")
        return 2
    capture.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ok, image = capture.read()
    capture.release()
    if not ok:
        print("Could not read a frame")
        return 2

    h, w = image.shape[:2]
    for i in range(1, 10):
        x, y = int(w * i / 10), int(h * i / 10)
        cv2.line(image, (x, 0), (x, h), _GRID, 1)
        cv2.line(image, (0, y), (w, y), _GRID, 1)
        cv2.putText(image, f"{i / 10:.1f}", (x + 2, h - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, _TEXT, 1)
        cv2.putText(image, f"{i / 10:.1f}", (2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, _TEXT, 1)

    frame = Frame(image=image, index=args.frame, timestamp_s=0.0,
                  captured_at=datetime.now(settings.tz))
    preview = FrameAnnotator(scene, settings.tz).draw(image, FrameAnalysis(frame, SceneSnapshot()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), preview)
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
