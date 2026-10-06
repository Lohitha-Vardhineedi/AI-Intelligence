"""Object detection. The pipeline only depends on `DetectionModel`, so another model
(ONNX, a different YOLO version, a cloud API) only needs a new adapter class."""

from __future__ import annotations

import logging
from collections.abc import Collection
from pathlib import Path
from typing import Protocol

import numpy as np

from app.ai.types import BoundingBox, Detection

logger = logging.getLogger(__name__)


class DetectionModel(Protocol):
    model_version: str

    def detect(self, frame: np.ndarray) -> list[Detection]: ...


class YoloDetectionModel:
    def __init__(
        self,
        model_path: Path,
        *,
        device: str,
        confidence_threshold: float,
        iou_threshold: float,
        image_size: int,
        classes: Collection[str] | None = None,
    ) -> None:
        from ultralytics import YOLO  # slow import, so it stays out of module load

        self._model = YOLO(str(model_path))
        self._names = {int(k): str(v) for k, v in self._model.names.items()}
        self._predict_args = {
            "conf": confidence_threshold,
            "iou": iou_threshold,
            "imgsz": image_size,
            "device": device,
            "half": device.startswith("cuda"),
            "classes": self._class_ids(classes),
            "verbose": False,
        }
        self.model_version = model_path.stem

    def _class_ids(self, classes: Collection[str] | None) -> list[int] | None:
        if not classes:
            return None
        by_name = {name: idx for idx, name in self._names.items()}
        unknown = sorted(c for c in classes if c not in by_name)
        if unknown:
            logger.warning("Ignoring classes this model does not know: %s", ", ".join(unknown))
        ids = sorted(by_name[c] for c in classes if c in by_name)
        if not ids:
            raise ValueError("None of the configured detection classes exist in the model")
        return ids

    def warm_up(self, width: int, height: int) -> None:
        """The first inference is slow (lazy init), so run it before the real frames."""
        self.detect(np.zeros((height, width, 3), dtype=np.uint8))

    def detect(self, frame: np.ndarray) -> list[Detection]:
        boxes = self._model.predict(frame, **self._predict_args)[0].boxes
        if boxes is None or len(boxes) == 0:
            return []
        # One device-to-host copy. Columns: x1, y1, x2, y2, confidence, class.
        rows = boxes.data[:, :6].cpu().numpy().tolist()
        return [
            Detection(int(cls), self._names[int(cls)], conf, BoundingBox(x1, y1, x2, y2))
            for x1, y1, x2, y2, conf, cls in rows
        ]


def resolve_device(requested: str) -> str:
    """'auto' picks a CUDA GPU, then Apple MPS, then the CPU."""
    if requested != "auto":
        return requested
    import torch

    if torch.cuda.is_available():
        return "cuda:0"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def ensure_model_file(path: Path) -> Path:
    """Download official Ultralytics weights (e.g. yolo11n.pt) on first use."""
    if path.exists():
        return path
    from ultralytics.utils.downloads import attempt_download_asset

    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading model weights to %s", path)
    downloaded = Path(attempt_download_asset(str(path)))
    if not downloaded.exists():
        raise FileNotFoundError(f"Model weights not found and could not be downloaded: {path}")
    return downloaded
