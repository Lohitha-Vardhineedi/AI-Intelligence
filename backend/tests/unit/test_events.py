from datetime import UTC

from app.events.detector import EventDetector
from app.events.types import EventType, Severity
from tests.helpers import make_frame, scene, tracked


def _run(positions_by_frame, scene_config=None):
    """positions_by_frame: list of lists of (track_id, x, y[, cls])."""
    detector = EventDetector(scene_config or scene(), UTC)
    events = []
    for index, objects in enumerate(positions_by_frame):
        frame = make_frame(index)
        result = detector.process(frame, [tracked(*obj) for obj in objects])
        events.extend(result.events)
    return detector, events


def _types(events):
    return [e.event_type for e in events]


def test_person_walking_into_room_raises_entry_and_intrusion_once():
    path = [[(7, 0.30 + i * 0.03, 0.5)] for i in range(20)]  # x 0.30 -> 0.87
    detector, events = _run(path)
    types = _types(events)
    assert types.count(EventType.PERSON_DETECTED) == 1
    assert types.count(EventType.LINE_CROSSED) == 1
    assert types.count(EventType.PERSON_ENTERED) == 1
    assert types.count(EventType.ZONE_ENTERED) == 1
    assert types.count(EventType.INTRUSION_DETECTED) == 1
    intrusion = next(e for e in events if e.event_type is EventType.INTRUSION_DETECTED)
    assert intrusion.severity is Severity.CRITICAL
    assert intrusion.track_id == 7
    assert intrusion.zone_name == "Room 101"
    assert detector.lines[0].in_count == 1
    assert detector.counter.unique == {"person": 1}


def test_walking_out_counts_exit():
    path = [[(1, 0.80 - i * 0.03, 0.5)] for i in range(20)]  # right -> left
    detector, events = _run(path)
    assert _types(events).count(EventType.PERSON_EXITED) == 1
    assert detector.lines[0].out_count == 1
    assert EventType.ZONE_EXITED in _types(events)


def test_jitter_on_the_line_is_not_counted():
    xs = [0.40, 0.45, 0.49, 0.51, 0.49, 0.51, 0.49, 0.51, 0.49, 0.45, 0.40]
    detector, events = _run([[(1, x, 0.5)] for x in xs])
    assert detector.lines[0].in_count == 0
    assert EventType.PERSON_ENTERED not in _types(events)


def test_crossing_beyond_the_end_of_the_line_is_ignored():
    short_line = scene(lines=[{"id": "door", "name": "Door", "start": [0.5, 0.6],
                               "end": [0.5, 0.4]}])
    detector, _ = _run([[(1, 0.30 + i * 0.05, 0.9)] for i in range(10)], short_line)
    assert detector.lines[0].in_count == 0


def test_track_lost_inside_zone_raises_exit():
    path = [[(1, 0.7, 0.5)] for _ in range(5)] + [[] for _ in range(25)]  # gone for 2.5 s
    _, events = _run(path)
    exits = [e for e in events if e.event_type is EventType.ZONE_EXITED]
    assert len(exits) == 1
    assert exits[0].details["reason"] == "track_lost"


def test_loitering_after_max_dwell():
    config = scene(zones=[{
        "id": "room", "name": "Room 101", "type": "RESTRICTED", "classes": ["person"],
        "max_dwell_seconds": 2, "min_frames_inside": 2,
        "points": [[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]],
    }])
    _, events = _run([[(1, 0.7, 0.5)] for _ in range(40)], config)  # 4 s inside
    assert _types(events).count(EventType.LOITERING_DETECTED) == 1


def test_bags_do_not_trigger_person_only_zone():
    path = [[(1, 0.30 + i * 0.03, 0.5, "handbag")] for i in range(20)]
    _, events = _run(path)
    assert EventType.INTRUSION_DETECTED not in _types(events)
    assert EventType.OBJECT_DETECTED in _types(events)


def test_crowd_detected_once_per_episode():
    config = scene(crowd={"max_people": 2, "min_duration_seconds": 0.5})
    crowd = [[(i, 0.1 + i * 0.05, 0.5) for i in range(1, 5)] for _ in range(20)]
    _, events = _run(crowd, config)
    assert _types(events).count(EventType.CROWD_DETECTED) == 1


def test_weak_detections_alone_never_confirm_an_object():
    """E.g. a rock that flickers as a 'dog' at 20-30% confidence."""
    detector = EventDetector(scene(), UTC, confirm_threshold=0.4)
    frames = [[tracked(9, 0.2, 0.3, "dog", conf=0.45)]] + [
        [tracked(9, 0.2, 0.3, "dog", conf=0.25)] for _ in range(30)
    ]
    for index, objects in enumerate(frames):
        result = detector.process(make_frame(index), objects)
        assert result.snapshot.tracks == []
    assert detector.counter.unique == {}


def test_class_specific_confidence_threshold():
    config = scene(detection={"class_confidence": {"animal": 0.6}})
    detector = EventDetector(config, UTC, confirm_threshold=0.4)
    for index in range(10):
        detector.process(make_frame(index), [tracked(1, 0.2, 0.3, "dog", conf=0.5),
                                             tracked(2, 0.3, 0.5, "person", conf=0.5)])
    assert detector.counter.unique == {"person": 1}  # dog at 50% < 60% is not counted


def test_counts_unique_and_peak_people():
    frames = [[(1, 0.1, 0.5), (2, 0.2, 0.5)] for _ in range(5)] + [[(3, 0.3, 0.5)]] * 5
    detector, _ = _run(frames)
    assert detector.counter.unique == {"person": 3}
    assert detector.counter.peak["person"] == 2
