from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.core.config import BACKEND_DIR

logger = logging.getLogger(__name__)

DEFAULT_VIDEO = BACKEND_DIR / "data" / "samples" / "vtest.avi"
DEFAULT_SCENE = BACKEND_DIR / "config" / "scene.yaml"
DEFAULT_OUTPUT = BACKEND_DIR / "output"
_SAMPLE_URL = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi"


def ensure_sample_video(source: str) -> None:
    """Download OpenCV's sample video the first time it is used."""
    if Path(source) != DEFAULT_VIDEO or DEFAULT_VIDEO.exists():
        return
    DEFAULT_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    partial = DEFAULT_VIDEO.with_suffix(".part")
    logger.info("Downloading the sample video from %s", _SAMPLE_URL)
    with httpx.stream("GET", _SAMPLE_URL, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        with partial.open("wb") as fh:
            for chunk in response.iter_bytes(chunk_size=1 << 16):
                fh.write(chunk)
    partial.replace(DEFAULT_VIDEO)
