import itertools

import numpy as np

from app.ai.matching import hungarian, linear_assignment
from app.ai.tracker import ByteTrackTracker
from tests.helpers import detection


def _brute_force(cost: np.ndarray) -> float:
    rows, cols = cost.shape
    if rows <= cols:
        return min(sum(cost[r, c] for r, c in zip(range(rows), perm, strict=False))
                   for perm in itertools.permutations(range(cols), rows))
    return _brute_force(cost.T)


def test_hungarian_matches_brute_force():
    rng = np.random.default_rng(7)
    for shape in [(3, 3), (3, 5), (5, 3), (4, 4)]:
        cost = rng.random(shape)
        pairs = hungarian(cost)
        assert len(pairs) == min(shape)
        assert np.isclose(sum(cost[r, c] for r, c in pairs), _brute_force(cost))


def test_linear_assignment_respects_threshold():
    cost = np.array([[0.1, 0.9], [0.95, 0.99]])
    matches, unmatched_rows, unmatched_cols = linear_assignment(cost, threshold=0.8)
    assert matches == [(0, 0)]
    assert unmatched_rows == [1]
    assert unmatched_cols == [1]


def test_same_person_keeps_the_same_id_while_moving():
    tracker = ByteTrackTracker(frame_rate=10)
    ids = set()
    for i in range(20):
        objects = tracker.update([detection(0.1 + i * 0.01, 0.5)])
        ids.update(o.track_id for o in objects)
    assert ids == {1}


def test_two_people_get_two_ids():
    tracker = ByteTrackTracker(frame_rate=10)
    for i in range(10):
        objects = tracker.update([detection(0.2 + i * 0.01, 0.5), detection(0.8 - i * 0.01, 0.5)])
    assert sorted(o.track_id for o in objects) == [1, 2]


def test_low_confidence_detection_keeps_track_alive():
    tracker = ByteTrackTracker(frame_rate=10, high_threshold=0.5, low_threshold=0.1)
    for i in range(5):
        tracker.update([detection(0.3 + i * 0.01, 0.5, conf=0.9)])
    # Partially occluded: confidence drops below the high threshold for a few frames.
    for i in range(5, 8):
        objects = tracker.update([detection(0.3 + i * 0.01, 0.5, conf=0.2)])
        assert [o.track_id for o in objects] == [1]
    objects = tracker.update([detection(0.38, 0.5, conf=0.9)])
    assert [o.track_id for o in objects] == [1]


def test_track_survives_a_short_gap():
    tracker = ByteTrackTracker(frame_rate=10, lost_buffer_seconds=1.0)
    for i in range(5):
        tracker.update([detection(0.3 + i * 0.01, 0.5)])
    for _ in range(4):  # missed for 0.4 s
        assert tracker.update([]) == []
    objects = tracker.update([detection(0.38, 0.5)])
    assert [o.track_id for o in objects] == [1]
