"""Draws AI results on frames: boxes, track IDs, labels, zones, lines, counts and alerts
(§30, §33)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import tzinfo

import cv2
import numpy as np

from app.events.detector import FrameAnalysis
from app.events.types import Alert, Severity
from app.schemas.scene import SceneConfig, ZoneType

Color = tuple[int, int, int]  # BGR

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_WHITE: Color = (255, 255, 255)
_BLACK: Color = (0, 0, 0)
_RED: Color = (40, 40, 230)
_YELLOW: Color = (0, 220, 255)
_ZONE_COLORS: dict[ZoneType, Color] = {
    ZoneType.RESTRICTED: (40, 40, 230),
    ZoneType.SAFE: (60, 180, 60),
    ZoneType.ENTRY: (230, 160, 30),
    ZoneType.EXIT: (230, 160, 30),
}
_CLASS_COLORS: dict[str, Color] = {
    "person": (80, 200, 80),
    "car": (230, 160, 30),
    "truck": (200, 120, 20),
    "bus": (200, 120, 20),
    "motorcycle": (220, 100, 160),
    "bicycle": (220, 100, 160),
}
_SEVERITY_COLORS: dict[Severity, Color] = {
    Severity.CRITICAL: (30, 30, 210),
    Severity.HIGH: (0, 120, 255),
    Severity.MEDIUM: (0, 190, 240),
    Severity.LOW: (200, 150, 40),
    Severity.INFO: (140, 140, 140),
}
_BANNER_SECONDS = 4.0


def _class_color(name: str) -> Color:
    if name in _CLASS_COLORS:
        return _CLASS_COLORS[name]
    h = sum(map(ord, name))
    return (60 + h * 37 % 180, 60 + h * 67 % 180, 60 + h * 97 % 180)


class FrameAnnotator:
    def __init__(self, scene: SceneConfig, tz: tzinfo) -> None:
        self._scene = scene
        self._tz = tz
        self._restricted = {z.id for z in scene.zones if z.type is ZoneType.RESTRICTED}

    def draw(
        self, image: np.ndarray, analysis: FrameAnalysis, alerts: Sequence[Alert] = ()
    ) -> np.ndarray:
        out = image.copy()
        h, w = out.shape[:2]
        scale = max(0.45, w / 1400)
        snapshot = analysis.snapshot
        if snapshot is None:
            return out

        self._draw_zones(out, snapshot.zone_occupancy, w, h, scale)
        self._draw_lines(out, snapshot.line_counts, w, h, scale)
        for track in snapshot.tracks:
            b = track.bbox
            p1, p2 = (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2))
            in_restricted = bool(track.zone_ids & self._restricted)
            color = _RED if in_restricted else _class_color(track.object_class)
            cv2.rectangle(out, p1, p2, color, 2)
            label = f"{track.object_class} #{track.track_id} {track.confidence:.0%}"
            _label(out, label, (p1[0], p1[1] - 4), color, scale)
            fx, fy = int(track.position[0] * w), int(track.position[1] * h)
            cv2.circle(out, (fx, fy), 3, color, -1)

        self._draw_hud(out, analysis, alerts, scale)
        self._draw_banner(out, analysis.frame.timestamp_s, alerts, scale)
        return out

    def _draw_zones(
        self, out: np.ndarray, occupancy: dict[str, int], w: int, h: int, scale: float
    ) -> None:
        overlay = out.copy()
        for zone in self._scene.zones:
            if not zone.enabled:
                continue
            pts = np.array([[x * w, y * h] for x, y in zone.points], dtype=np.int32)
            color = _ZONE_COLORS.get(zone.type, (200, 200, 0))
            cv2.fillPoly(overlay, [pts], color)
        cv2.addWeighted(overlay, 0.18, out, 0.82, 0, out)
        for zone in self._scene.zones:
            if not zone.enabled:
                continue
            pts = np.array([[x * w, y * h] for x, y in zone.points], dtype=np.int32)
            color = _ZONE_COLORS.get(zone.type, (200, 200, 0))
            cv2.polylines(out, [pts], True, color, 2)
            corner = min(pts, key=lambda p: int(p[0]) + int(p[1]))  # top-left-most vertex
            text = f"{zone.name} [{zone.type.value}] inside: {occupancy.get(zone.id, 0)}"
            _label(out, text, (int(corner[0]), int(corner[1]) - 6), color, scale)

    def _draw_lines(
        self, out: np.ndarray, counts: dict[str, tuple[int, int]], w: int, h: int, scale: float
    ) -> None:
        for line in self._scene.lines:
            if not line.enabled:
                continue
            a = (int(line.start[0] * w), int(line.start[1] * h))
            b = (int(line.end[0] * w), int(line.end[1] * h))
            cv2.line(out, a, b, _YELLOW, 2)
            # Arrow pointing to the IN side (right-hand side of A->B on screen).
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy) or 1.0
            mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
            tip = (int(mid[0] - dy / length * 35), int(mid[1] + dx / length * 35))
            cv2.arrowedLine(out, mid, tip, _YELLOW, 2, tipLength=0.4)
            n_in, n_out = counts.get(line.id, (0, 0))
            _label(out, f"{line.name}  IN {n_in} | OUT {n_out}", (tip[0] + 6, tip[1]), _YELLOW,
                   scale)

    def _draw_hud(
        self, out: np.ndarray, analysis: FrameAnalysis, alerts: Sequence[Alert], scale: float
    ) -> None:
        snapshot = analysis.snapshot
        assert snapshot is not None
        frame = analysis.frame
        camera = self._scene.camera
        people_now = snapshot.current_counts.get("person", 0)
        others = [
            f"{cls} {n}" for cls, n in snapshot.current_counts.most_common() if cls != "person"
        ]
        lines = [
            f"{camera.name}  |  {camera.location}" if camera.location else camera.name,
            frame.captured_at.astimezone(self._tz).strftime("%d %b %Y %H:%M:%S")
            + f"   video {int(frame.timestamp_s // 60):02d}:{frame.timestamp_s % 60:04.1f}",
            f"People now: {people_now}   Unique people: {snapshot.unique_counts.get('person', 0)}",
            "Objects now: " + (", ".join(others[:4]) if others else "none"),
        ]
        for line in self._scene.lines:
            n_in, n_out = snapshot.line_counts.get(line.id, (0, 0))
            lines.append(f"{line.name}: IN {n_in}  OUT {n_out}")
        lines.append(f"Alerts: {len(alerts)}")

        line_h = int(26 * scale + 8)
        box_w = int(max(cv2.getTextSize(t, _FONT, 0.5 * scale + 0.1, 1)[0][0] for t in lines) + 20)
        box_h = line_h * len(lines) + 10
        top = 8
        region = out[top : top + box_h, 8 : 8 + box_w]
        region[:] = (region * 0.35).astype(np.uint8)
        for i, text in enumerate(lines):
            y = top + 8 + line_h * (i + 1) - 6
            weight = 2 if i == 2 else 1
            cv2.putText(out, text, (18, y), _FONT, 0.5 * scale + 0.1, _WHITE, weight, cv2.LINE_AA)

    def _draw_banner(
        self, out: np.ndarray, now_s: float, alerts: Sequence[Alert], scale: float
    ) -> None:
        recent = [a for a in alerts if 0 <= now_s - a.stream_time_s <= _BANNER_SECONDS]
        if not recent:
            return
        alert = recent[-1]
        h, w = out.shape[:2]
        bar_h = int(34 * scale + 14)
        color = _SEVERITY_COLORS.get(alert.severity, _RED)
        cv2.rectangle(out, (0, h - bar_h), (w, h), color, -1)
        where = alert.event.zone_name or self._scene.camera.name
        sms = "  |  SMS sent" if alert.notify_sms else ""
        text = f"ALERT [{alert.severity.value}] {alert.event.title} - {where}{sms}"
        cv2.putText(out, text, (12, h - bar_h // 2 + 6), _FONT, 0.6 * scale + 0.1, _WHITE, 2,
                    cv2.LINE_AA)


def _label(img: np.ndarray, text: str, origin: tuple[int, int], color: Color, scale: float) -> None:
    font_scale = 0.45 * scale + 0.05
    (tw, th), baseline = cv2.getTextSize(text, _FONT, font_scale, 1)
    x = max(0, min(origin[0], img.shape[1] - tw - 4))
    y = max(th + 4, origin[1])
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + baseline - 2), color, -1)
    cv2.putText(img, text, (x + 2, y - 2), _FONT, font_scale, _BLACK, 1, cv2.LINE_AA)
