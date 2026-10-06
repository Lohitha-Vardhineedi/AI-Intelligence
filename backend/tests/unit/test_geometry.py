from app.events.geometry import (
    point_in_polygon,
    polygon_is_simple,
    segments_intersect,
    side_of_line,
)

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def test_side_of_line_uses_screen_right_hand_side():
    # Line pointing up the screen (y decreases): its right-hand side is screen-right.
    a, b = (0.5, 1.0), (0.5, 0.0)
    assert side_of_line(a, b, (0.7, 0.5)) == 1
    assert side_of_line(a, b, (0.3, 0.5)) == -1
    assert side_of_line(a, b, (0.501, 0.5), tolerance=0.01) == 0


def test_segments_intersect():
    assert segments_intersect((0, 0), (1, 1), (0, 1), (1, 0))
    assert not segments_intersect((0, 0), (0.4, 0.4), (0, 1), (1, 0.9))
    assert segments_intersect((0, 0), (0.5, 0.5), (0.5, 0.5), (1, 0))  # touching end point
    assert not segments_intersect((0, 0), (1, 0), (0, 1), (1, 1))  # parallel


def test_point_in_polygon():
    assert point_in_polygon((0.5, 0.5), SQUARE)
    assert not point_in_polygon((0.1, 0.5), SQUARE)
    assert not point_in_polygon((0.5, 0.9), SQUARE)


def test_polygon_is_simple():
    assert polygon_is_simple(SQUARE)
    bow_tie = [(0.2, 0.2), (0.8, 0.8), (0.8, 0.2), (0.2, 0.8)]
    assert not polygon_is_simple(bow_tie)
