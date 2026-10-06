"""Constant-velocity Kalman filter for boxes, as used by SORT and ByteTrack.

State: (cx, cy, aspect ratio, height) and their velocities.
"""

from __future__ import annotations

import numpy as np

_NDIM = 4
_POSITION_WEIGHT = 1.0 / 20
_VELOCITY_WEIGHT = 1.0 / 160


class KalmanFilter:
    def __init__(self) -> None:
        self._motion = np.eye(2 * _NDIM)
        self._motion[:_NDIM, _NDIM:] = np.eye(_NDIM)
        self._update = np.eye(_NDIM, 2 * _NDIM)
        self._diag = np.arange(2 * _NDIM)

    def initiate(self, measurement: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean = np.concatenate([measurement, np.zeros(_NDIM)])
        h = measurement[3]
        pos, vel = 2 * _POSITION_WEIGHT * h, 10 * _VELOCITY_WEIGHT * h
        std = np.array([pos, pos, 1e-2, pos, vel, vel, 1e-5, vel])
        return mean, np.diag(std * std)

    def multi_predict(
        self, mean: np.ndarray, covariance: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Predict all tracks in one go: mean is (N, 8), covariance is (N, 8, 8)."""
        h = mean[:, 3]
        pos, vel = _POSITION_WEIGHT * h, _VELOCITY_WEIGHT * h
        std = np.stack(
            [pos, pos, np.full_like(h, 1e-2), pos, vel, vel, np.full_like(h, 1e-5), vel], axis=1
        )
        motion_cov = np.zeros_like(covariance)
        motion_cov[:, self._diag, self._diag] = std * std
        mean = mean @ self._motion.T
        covariance = self._motion @ covariance @ self._motion.T + motion_cov
        return mean, covariance

    def update(
        self, mean: np.ndarray, covariance: np.ndarray, measurement: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        pos = _POSITION_WEIGHT * mean[3]
        noise = np.diag(np.array([pos, pos, 1e-1, pos]) ** 2)
        projected_mean = self._update @ mean
        projected_cov = self._update @ covariance @ self._update.T + noise
        gain = np.linalg.solve(projected_cov, (covariance @ self._update.T).T).T
        new_mean = mean + (measurement - projected_mean) @ gain.T
        new_covariance = covariance - gain @ projected_cov @ gain.T
        return new_mean, new_covariance
