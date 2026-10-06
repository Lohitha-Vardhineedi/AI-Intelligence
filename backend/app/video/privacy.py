from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from app.events.geometry import Point


class PrivacyMask:
    """Blacks out regions (normalised polygons) before a frame is analysed, saved or shown.

    The pixel mask is built once per frame size rather than on every frame.
    """

    def __init__(self, polygons: Sequence[Sequence[Point]]) -> None:
        self._polygons = [np.asarray(p, dtype=np.float64) for p in polygons]
        self._mask: np.ndarray | None = None

    def apply(self, image: np.ndarray) -> np.ndarray:
        """Masks `image` in place and returns it."""
        if not self._polygons:
            return image
        height, width = image.shape[:2]
        if self._mask is None or self._mask.shape != (height, width):
            mask = np.zeros((height, width), dtype=np.uint8)
            scale = np.array([width, height])
            cv2.fillPoly(mask, [(p * scale).astype(np.int32) for p in self._polygons], 255)
            self._mask = mask.astype(bool)
        image[self._mask] = 0
        return image
