"""Config can use COCO class names ("car") or group names ("vehicle")."""

from __future__ import annotations

from collections.abc import Iterable

CLASS_GROUPS: dict[str, tuple[str, ...]] = {
    "person": ("person",),
    "vehicle": ("bicycle", "car", "motorcycle", "bus", "truck"),
    "animal": (
        "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe",
    ),
    "bag": ("backpack", "handbag", "suitcase"),
}


def expand_classes(names: Iterable[str]) -> set[str]:
    """Expand group names into class names. Unknown names are kept as they are."""
    expanded: set[str] = set()
    for name in names:
        key = name.strip().lower()
        expanded.update(CLASS_GROUPS.get(key, (key,)))
    return expanded
