"""Multi-object tracking with ByteTrack (Zhang et al., 2021).

High-confidence detections create and update tracks. Low-confidence detections are only
used to keep existing tracks alive, e.g. when a person is partly hidden. That keeps the
same ID on the same person, so they are not counted twice.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum
from typing import Protocol

import numpy as np

from app.ai.kalman_filter import KalmanFilter
from app.ai.matching import iou_matrix, linear_assignment
from app.ai.types import BoundingBox, Detection, TrackedObject


class ObjectTracker(Protocol):
    def update(self, detections: Sequence[Detection]) -> list[TrackedObject]: ...


class _State(IntEnum):
    NEW = 0
    TRACKED = 1
    LOST = 2
    REMOVED = 3


def _xyxy_to_xyah(box: np.ndarray) -> np.ndarray:
    w, h = box[2] - box[0], max(box[3] - box[1], 1e-6)
    return np.array([box[0] + w / 2, box[1] + h / 2, w / h, h])


class _Track:
    __slots__ = (
        "box", "class_id", "class_name", "covariance", "frame_id", "is_activated", "mean",
        "score", "start_frame", "state", "track_id",
    )

    def __init__(self, detection: Detection) -> None:
        b = detection.bbox
        self.box = np.array([b.x1, b.y1, b.x2, b.y2])  # last matched detection
        self.score = detection.confidence
        self.class_id = detection.class_id
        self.class_name = detection.class_name
        self.mean: np.ndarray | None = None
        self.covariance: np.ndarray | None = None
        self.track_id = 0
        self.state = _State.NEW
        self.is_activated = False
        self.frame_id = 0
        self.start_frame = 0

    @property
    def predicted_box(self) -> np.ndarray:
        if self.mean is None:
            return self.box
        cx, cy, a, h = self.mean[:4]
        w = a * h
        return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])

    def activate(self, kf: KalmanFilter, frame_id: int, track_id: int) -> None:
        self.track_id = track_id
        self.mean, self.covariance = kf.initiate(_xyxy_to_xyah(self.box))
        self.state = _State.TRACKED
        self.is_activated = frame_id == 1  # otherwise confirmed by its next match
        self.frame_id = self.start_frame = frame_id

    def update(self, kf: KalmanFilter, det: _Track, frame_id: int) -> None:
        self.mean, self.covariance = kf.update(self.mean, self.covariance, _xyxy_to_xyah(det.box))
        self.box = det.box
        self.score = det.score
        self.class_id, self.class_name = det.class_id, det.class_name
        self.state = _State.TRACKED
        self.is_activated = True
        self.frame_id = frame_id


def _distance(tracks: Sequence[_Track], dets: Sequence[_Track]) -> np.ndarray:
    """1 - IoU. Pairs of different classes can never match."""
    if not tracks or not dets:
        return np.zeros((len(tracks), len(dets)))
    iou = iou_matrix(np.array([t.predicted_box for t in tracks]), np.array([d.box for d in dets]))
    track_classes = np.array([t.class_id for t in tracks])
    det_classes = np.array([d.class_id for d in dets])
    return np.where(track_classes[:, None] == det_classes[None, :], 1.0 - iou, 1.0)


def _unique(tracks: Sequence[_Track]) -> list[_Track]:
    seen: set[int] = set()
    result: list[_Track] = []
    for track in tracks:
        if track.track_id not in seen:
            seen.add(track.track_id)
            result.append(track)
    return result


class ByteTrackTracker:
    def __init__(
        self,
        *,
        frame_rate: float,
        high_threshold: float = 0.4,
        low_threshold: float = 0.1,
        match_threshold: float = 0.8,
        lost_buffer_seconds: float = 1.5,
    ) -> None:
        self._high = high_threshold
        self._low = low_threshold
        self._match = match_threshold
        self._max_lost_frames = max(1, round(frame_rate * lost_buffer_seconds))
        self._kf = KalmanFilter()
        self._tracked: list[_Track] = []
        self._lost: list[_Track] = []
        self._frame_id = 0
        self._next_id = 0

    def update(self, detections: Sequence[Detection]) -> list[TrackedObject]:
        self._frame_id += 1
        frame_id = self._frame_id
        high = [_Track(d) for d in detections if d.confidence >= self._high]
        low = [_Track(d) for d in detections if self._low <= d.confidence < self._high]

        unconfirmed = [t for t in self._tracked if not t.is_activated]
        pool = _unique([t for t in self._tracked if t.is_activated] + self._lost)
        self._predict(pool)

        activated: list[_Track] = []
        newly_lost: list[_Track] = []
        removed: list[_Track] = []

        # 1. Confirmed and lost tracks against high-confidence detections.
        matches, unmatched_tracks, unmatched_high = linear_assignment(
            _distance(pool, high), self._match
        )
        for ti, di in matches:
            pool[ti].update(self._kf, high[di], frame_id)
            activated.append(pool[ti])

        # 2. Tracks still unmatched against low-confidence detections.
        remaining = [pool[i] for i in unmatched_tracks if pool[i].state == _State.TRACKED]
        matches, still_unmatched, _ = linear_assignment(_distance(remaining, low), 0.5)
        for ti, di in matches:
            remaining[ti].update(self._kf, low[di], frame_id)
            activated.append(remaining[ti])
        for ti in still_unmatched:
            remaining[ti].state = _State.LOST
            newly_lost.append(remaining[ti])

        # 3. Tracks started last frame against the high detections left over.
        leftover = [high[i] for i in unmatched_high]
        matches, unmatched_unconfirmed, unmatched_leftover = linear_assignment(
            _distance(unconfirmed, leftover), 0.7
        )
        for ti, di in matches:
            unconfirmed[ti].update(self._kf, leftover[di], frame_id)
            activated.append(unconfirmed[ti])
        for ti in unmatched_unconfirmed:
            unconfirmed[ti].state = _State.REMOVED
            removed.append(unconfirmed[ti])

        # 4. Anything still unmatched starts a new track.
        for di in unmatched_leftover:
            det = leftover[di]
            self._next_id += 1
            det.activate(self._kf, frame_id, self._next_id)
            activated.append(det)

        # 5. Forget tracks that have been lost for too long.
        for track in self._lost:
            if frame_id - track.frame_id > self._max_lost_frames:
                track.state = _State.REMOVED
                removed.append(track)

        removed_ids = {id(t) for t in removed}
        self._tracked = _unique(
            [t for t in self._tracked if t.state == _State.TRACKED] + activated
        )
        tracked_ids = {t.track_id for t in self._tracked}
        self._lost = [
            t
            for t in _unique(self._lost + newly_lost)
            if t.track_id not in tracked_ids and id(t) not in removed_ids
            and t.state == _State.LOST
        ]
        self._remove_duplicates()

        return [
            TrackedObject(
                track_id=t.track_id,
                class_id=t.class_id,
                class_name=t.class_name,
                confidence=float(t.score),
                bbox=BoundingBox(*t.box.tolist()),
            )
            for t in self._tracked
            if t.is_activated and t.frame_id == frame_id
        ]

    def _predict(self, tracks: list[_Track]) -> None:
        """One batched Kalman prediction for every track, instead of one call per track."""
        if not tracks:
            return
        mean = np.array([t.mean for t in tracks])
        covariance = np.array([t.covariance for t in tracks])
        # A lost track's height shouldn't keep growing or shrinking while it is unseen.
        mean[[t.state != _State.TRACKED for t in tracks], 7] = 0.0
        mean, covariance = self._kf.multi_predict(mean, covariance)
        for track, m, c in zip(tracks, mean, covariance, strict=True):
            track.mean, track.covariance = m, c

    def _remove_duplicates(self) -> None:
        """When a tracked and a lost track overlap almost completely, drop the younger one."""
        if not self._tracked or not self._lost:
            return
        distance = _distance(self._tracked, self._lost)
        drop_tracked, drop_lost = set(), set()
        for ti, li in zip(*np.nonzero(distance < 0.15), strict=True):
            t, lost = self._tracked[ti], self._lost[li]
            if t.frame_id - t.start_frame > lost.frame_id - lost.start_frame:
                drop_lost.add(li)
            else:
                drop_tracked.add(ti)
        self._tracked = [t for i, t in enumerate(self._tracked) if i not in drop_tracked]
        self._lost = [t for i, t in enumerate(self._lost) if i not in drop_lost]
