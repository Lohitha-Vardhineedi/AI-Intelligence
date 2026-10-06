from datetime import UTC

import cv2
import numpy as np
import pytest

from app.events.detector import FrameAnalysis, SceneSnapshot
from app.video.annotator import FrameAnnotator
from app.video.privacy import PrivacyMask
from app.video.sources import FileVideoSource, frame_step, redact_url
from app.video.writer import AnnotatedVideoWriter
from tests.helpers import make_frame, scene


@pytest.mark.parametrize(
    ("source_fps", "inference_fps", "frame_skip", "expected"),
    [(30, 10, None, 3), (25, 10, None, 2), (10, 10, None, 1), (5, 10, None, 1), (30, 10, 0, 1),
     (30, None, 4, 5), (30, None, None, 1)],
)
def test_frame_step(source_fps, inference_fps, frame_skip, expected):
    assert frame_step(source_fps, inference_fps, frame_skip) == expected


def test_file_source_skips_frames_but_keeps_their_index_and_time(tmp_path):
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (64, 48))
    for i in range(10):
        writer.write(np.full((48, 64, 3), i * 20, dtype=np.uint8))
    writer.release()

    source = FileVideoSource(path, UTC, inference_fps=10)
    source.open()
    frames = []
    while (frame := source.read()) is not None:
        frames.append(frame)
    source.close()

    assert source.effective_fps == 10
    assert [f.index for f in frames] == [0, 3, 6, 9]
    assert frames[1].timestamp_s == pytest.approx(0.1)
    assert source.frames_read == 10


def test_privacy_mask_blacks_out_only_the_polygon():
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    PrivacyMask([[(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)]]).apply(image)
    assert image[10, 10].tolist() == [0, 0, 0]
    assert image[90, 190].tolist() == [255, 255, 255]


def test_redact_camera_url():
    url = "rtsp://admin:s3cret@192.168.1.20:554/stream1"
    assert redact_url(url) == "rtsp://***@192.168.1.20:554/stream1"


def test_annotator_tints_zones_only_and_leaves_the_input_untouched():
    image = np.zeros((1000, 1000, 3), dtype=np.uint8)
    frame = make_frame(0)
    frame.image = image
    out = FrameAnnotator(scene(), UTC).draw(image, FrameAnalysis(frame, SceneSnapshot()))
    assert out[600, 800].any()  # inside the room zone (x > 0.5)
    assert not out[600, 300].any()  # outside it, below the HUD
    assert not image.any()


def test_annotated_writer_produces_a_readable_video(tmp_path):
    path = tmp_path / "annotated.mp4"
    writer = AnnotatedVideoWriter(path, 10, (64, 48))
    for i in range(10):
        writer.write(np.full((48, 64, 3), i * 20, dtype=np.uint8))
    writer.close()

    capture = cv2.VideoCapture(str(path))
    frames = 0
    while capture.read()[0]:
        frames += 1
    capture.release()
    assert frames == 10
