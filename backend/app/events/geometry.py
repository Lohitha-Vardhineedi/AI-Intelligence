"""2-D geometry for line-crossing and zone detection.

Coordinates are normalised to the frame: x and y in [0, 1], origin top-left, y pointing
down (the OpenCV convention). Normalised coordinates keep zones valid if the camera
resolution changes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]

_EPS = 1e-12


def cross(o: Point, a: Point, b: Point) -> float:
    """Z-component of (a - o) x (b - o)."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def signed_distance(a: Point, b: Point, p: Point) -> float:
    """Signed distance from p to the line through a->b.

    Positive = right-hand side of a->b as seen on screen (because y points down).
    """
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    return cross(a, b, p) / length if length > _EPS else 0.0


def side_of_line(a: Point, b: Point, p: Point, tolerance: float = 0.0) -> int:
    """+1 right side, -1 left side, 0 within `tolerance` of the line."""
    d = signed_distance(a, b, p)
    if d > tolerance:
        return 1
    if d < -tolerance:
        return -1
    return 0


def _on_segment(p: Point, q: Point, r: Point) -> bool:
    """True if q lies within the bounding box of segment p-r (assumes collinear)."""
    return (
        min(p[0], r[0]) - _EPS <= q[0] <= max(p[0], r[0]) + _EPS
        and min(p[1], r[1]) - _EPS <= q[1] <= max(p[1], r[1]) + _EPS
    )


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """True if segment p1-p2 intersects segment q1-q2 (touching counts)."""
    d1, d2 = cross(q1, q2, p1), cross(q1, q2, p2)
    d3, d4 = cross(p1, p2, q1), cross(p1, p2, q2)
    if ((d1 > _EPS and d2 < -_EPS) or (d1 < -_EPS and d2 > _EPS)) and (
        (d3 > _EPS and d4 < -_EPS) or (d3 < -_EPS and d4 > _EPS)
    ):
        return True
    return (
        (abs(d1) <= _EPS and _on_segment(q1, p1, q2))
        or (abs(d2) <= _EPS and _on_segment(q1, p2, q2))
        or (abs(d3) <= _EPS and _on_segment(p1, q1, p2))
        or (abs(d4) <= _EPS and _on_segment(p1, q2, p2))
    )


def point_in_polygon(p: Point, polygon: Sequence[Point]) -> bool:
    """Ray-casting test. Points exactly on an edge may fall either way."""
    x, y = p
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < xi + (y - yi) * (xj - xi) / (yj - yi):
            inside = not inside
        j = i
    return inside


def polygon_is_simple(polygon: Sequence[Point]) -> bool:
    """True if no two non-adjacent edges intersect (no self-crossing)."""
    n = len(polygon)
    edges = [(polygon[i], polygon[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # adjacent edges share a vertex
            if segments_intersect(*edges[i], *edges[j]):
                return False
    return True
