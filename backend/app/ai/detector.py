"""Object detection. The pipeline only depends on `DetectionModel`, so another model
(a different YOLO version, a cloud API) only needs a new adapter class.

Two adapters are included:
- `YoloDetectionModel`: Ultralytics with PyTorch, for `.pt` weights. CUDA GPUs are used
  when available.
- `OnnxDetectionModel`: the same YOLO weights exported to ONNX and run with ONNX Runtime.
  It needs neither PyTorch nor Ultralytics, so it fits small containers (512 MB).
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.ai.types import BoundingBox, Detection

logger = logging.getLogger(__name__)


class DetectionModel(Protocol):
    model_version: str

    def detect(self, frame: np.ndarray) -> list[Detection]: ...


def class_ids(names: Mapping[int, str], classes: Collection[str] | None) -> list[int] | None:
    """Model class IDs for the configured class names. None means every class."""
    if not classes:
        return None
    by_name = {name: idx for idx, name in names.items()}
    unknown = sorted(c for c in classes if c not in by_name)
    if unknown:
        logger.warning("Ignoring classes this model does not know: %s", ", ".join(unknown))
    ids = sorted(by_name[c] for c in classes if c in by_name)
    if not ids:
        raise ValueError("None of the configured detection classes exist in the model")
    return ids


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
            "classes": class_ids(self._names, classes),
            "verbose": False,
        }
        self.model_version = model_path.stem

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


class OnnxDetectionModel:
    """A YOLO model exported with `yolo export format=onnx dynamic=True`.

    Pre- and post-processing follow Ultralytics: the frame is resized with grey padding to
    a multiple of 32 (letterbox), and overlapping boxes of the same class are merged (NMS).
    """

    _STRIDE = 32
    _MAX_DETECTIONS = 300

    def __init__(
        self,
        model_path: Path,
        *,
        confidence_threshold: float,
        iou_threshold: float,
        image_size: int,
        classes: Collection[str] | None = None,
        threads: int = 0,
    ) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        if threads > 0:  # on a small CPU share, extra threads only add overhead
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name
        metadata = self._session.get_modelmeta().custom_metadata_map
        self._names = {int(k): str(v) for k, v in ast.literal_eval(metadata["names"]).items()}
        ids = class_ids(self._names, classes)
        self._class_mask = None if ids is None else np.isin(np.arange(len(self._names)), ids)
        self._confidence = confidence_threshold
        self._iou = iou_threshold
        self._size = max(self._STRIDE, image_size // self._STRIDE * self._STRIDE)
        self.model_version = model_path.stem

    def warm_up(self, width: int, height: int) -> None:
        self.detect(np.zeros((height, width, 3), dtype=np.uint8))

    def detect(self, frame: np.ndarray) -> list[Detection]:
        blob, gain, pad_x, pad_y = self._letterbox(frame)
        # Rows: cx, cy, w, h in model-input pixels, then one score per class.
        output = self._session.run(None, {self._input: blob})[0][0].T
        scores = output[:, 4:]
        if self._class_mask is not None:
            scores = scores * self._class_mask
        class_id = scores.argmax(axis=1)
        confidence = scores[np.arange(len(scores)), class_id]
        keep = confidence >= self._confidence
        if not keep.any():
            return []
        boxes, confidence, class_id = output[keep, :4], confidence[keep], class_id[keep]

        # Back to frame pixels, as (x, y, w, h) for OpenCV's NMS.
        xywh = np.empty_like(boxes)
        xywh[:, 0] = (boxes[:, 0] - boxes[:, 2] / 2 - pad_x) / gain
        xywh[:, 1] = (boxes[:, 1] - boxes[:, 3] / 2 - pad_y) / gain
        xywh[:, 2:] = boxes[:, 2:] / gain
        selected = cv2.dnn.NMSBoxesBatched(xywh, confidence, class_id, self._confidence, self._iou)

        height, width = frame.shape[:2]
        detections = []
        for i in np.asarray(selected, dtype=int).reshape(-1)[: self._MAX_DETECTIONS]:
            x, y, w, h = xywh[i].tolist()
            cls = int(class_id[i])
            box = BoundingBox(
                max(0.0, x), max(0.0, y), min(float(width), x + w), min(float(height), y + h)
            )
            detections.append(Detection(cls, self._names[cls], float(confidence[i]), box))
        return detections

    def _letterbox(self, frame: np.ndarray) -> tuple[np.ndarray, float, int, int]:
        height, width = frame.shape[:2]
        gain = min(self._size / height, self._size / width)
        new_w, new_h = round(width * gain), round(height * gain)
        # Pad only up to the next multiple of 32, so the input stays rectangular.
        pad_w = (self._size - new_w) % self._STRIDE / 2
        pad_h = (self._size - new_h) % self._STRIDE / 2
        image = frame
        if (new_w, new_h) != (width, height):
            image = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        left, top = round(pad_w - 0.1), round(pad_h - 0.1)
        image = cv2.copyMakeBorder(
            image, top, round(pad_h + 0.1), left, round(pad_w + 0.1),
            cv2.BORDER_CONSTANT, value=(114, 114, 114),
        )
        blob = cv2.dnn.blobFromImage(image, 1 / 255.0, swapRB=True)  # NCHW, RGB, 0-1
        return blob, gain, left, top


def load_detection_model(
    model_path: Path,
    *,
    device: str,
    confidence_threshold: float,
    iou_threshold: float,
    image_size: int,
    classes: Collection[str] | None,
    threads: int = 0,
) -> YoloDetectionModel | OnnxDetectionModel:
    """Picks the adapter from the file type: .onnx for ONNX Runtime, otherwise Ultralytics."""
    if model_path.suffix == ".onnx":
        if not model_path.exists():
            raise FileNotFoundError(
                f"{model_path} not found. Export it with: "
                "yolo export model=yolo11n.pt format=onnx dynamic=True"
            )
        logger.info("Loading detection model %s with ONNX Runtime", model_path.name)
        return OnnxDetectionModel(
            model_path,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            image_size=image_size,
            classes=classes,
            threads=threads,
        )
    model_path = ensure_model_file(model_path)
    device = resolve_device(device)
    logger.info("Loading detection model %s on %s", model_path.name, device)
    return YoloDetectionModel(
        model_path,
        device=device,
        confidence_threshold=confidence_threshold,
        iou_threshold=iou_threshold,
        image_size=image_size,
        classes=classes,
    )


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
