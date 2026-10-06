"""Assignment helpers for tracking, in plain NumPy (no SciPy dependency)."""

from __future__ import annotations

import numpy as np

_INVALID_COST = 1e6


def iou_matrix(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between two sets of (x1, y1, x2, y2) boxes."""
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.zeros((len(boxes_a), len(boxes_b)), dtype=np.float64)
    top_left = np.maximum(boxes_a[:, None, :2], boxes_b[None, :, :2])
    bottom_right = np.minimum(boxes_a[:, None, 2:], boxes_b[None, :, 2:])
    wh = np.clip(bottom_right - top_left, 0.0, None)
    intersection = wh[..., 0] * wh[..., 1]
    area_a = (boxes_a[:, 2] - boxes_a[:, 0]) * (boxes_a[:, 3] - boxes_a[:, 1])
    area_b = (boxes_b[:, 2] - boxes_b[:, 0]) * (boxes_b[:, 3] - boxes_b[:, 1])
    union = area_a[:, None] + area_b[None, :] - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)


def hungarian(cost: np.ndarray) -> list[tuple[int, int]]:
    """Minimum-cost assignment for a rectangular matrix (Kuhn-Munkres, O(n^2 m)).

    Returns (row, column) pairs. When rows <= columns every row is assigned.
    """
    transposed = cost.shape[0] > cost.shape[1]
    matrix = (cost.T if transposed else cost).tolist()
    n, m = len(matrix), len(matrix[0]) if matrix else 0
    if n == 0 or m == 0:
        return []

    inf = float("inf")
    u = [0.0] * (n + 1)  # row potentials
    v = [0.0] * (m + 1)  # column potentials
    p = [0] * (m + 1)  # p[j]: row (1-based) assigned to column j
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        min_v = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            row = matrix[i0 - 1]
            for j in range(1, m + 1):
                if not used[j]:
                    current = row[j - 1] - u[i0] - v[j]
                    if current < min_v[j]:
                        min_v[j], way[j] = current, j0
                    if min_v[j] < delta:
                        delta, j1 = min_v[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    min_v[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    pairs = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j]]
    return [(c, r) for r, c in pairs] if transposed else pairs


def linear_assignment(
    cost: np.ndarray, threshold: float
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Optimal assignment that never pairs anything costing more than `threshold`.

    Returns (matches, unmatched_rows, unmatched_columns).
    """
    rows, cols = cost.shape
    if rows == 0 or cols == 0:
        return [], list(range(rows)), list(range(cols))
    masked = np.where(cost > threshold, _INVALID_COST, cost)
    matches = [(r, c) for r, c in hungarian(masked) if cost[r, c] <= threshold]
    matched_rows = {r for r, _ in matches}
    matched_cols = {c for _, c in matches}
    return (
        matches,
        [r for r in range(rows) if r not in matched_rows],
        [c for c in range(cols) if c not in matched_cols],
    )
