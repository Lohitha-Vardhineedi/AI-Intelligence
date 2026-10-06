"""Draws boxes, track IDs, zones, lines, counts and alert banners on a frame."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import tzinfo

import cv2
import numpy as np

from app.events.detector import FrameAnalysis
from app.events.track_state import TrackState
from app.events.types import Alert, Severity
from app.schemas.scene import LineConfig, SceneConfig, ZoneConfig, ZoneType

Color = tuple[int, int, int]  # BGR
Pixel = tuple[int, int]

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_WHITE: Color = (255, 255, 255)
_BLACK: Color = (0, 0, 0)
_RED: Color = (40, 40, 230)
_YELLOW: Color = (0, 220, 255)
_ZONE_OPACITY = 0.18
_BANNER_SECONDS = 4.0
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


def _class_color(name: str) -> Color:
    if name in _CLASS_COLORS:
        return _CLASS_COLORS[name]
    h = sum(map(ord, name))
    return (60 + h * 37 % 180, 60 + h * 67 % 180, 60 + h * 97 % 180)


def _zone_color(zone: ZoneConfig) -> Color:
    return _ZONE_COLORS.get(zone.type, (200, 200, 0))


@dataclass(slots=True)
class _Layout:
    """Zones and lines in pixels. They don't move, so this is built once per frame size."""

    size: Pixel
    zones: list[tuple[ZoneConfig, np.ndarray]]
    lines: list[tuple[LineConfig, Pixel, Pixel, Pixel, Pixel]]  # line, A, B, arrow from, to
    fill_roi: tuple[slice, slice] | None  # box around all zones; blending stays inside it
    fill_layer: np.ndarray | None  # zone colours
    fill_mask: np.ndarray | None  # 255 inside a zone

    @classmethod
    def build(
        cls, zones: Sequence[ZoneConfig], lines: Sequence[LineConfig], width: int, height: int
    ) -> _Layout:
        zone_pixels = [
            (zone, np.array([[x * width, y * height] for x, y in zone.points], dtype=np.int32))
            for zone in zones
        ]
        layer = np.zeros((height, width, 3), dtype=np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        for zone, pts in zone_pixels:
            cv2.fillPoly(layer, [pts], _zone_color(zone))
            cv2.fillPoly(mask, [pts], 255)
        x, y, w, h = cv2.boundingRect(mask)
        roi = (slice(y, y + h), slice(x, x + w)) if w and h else None

        line_pixels = []
        for line in lines:
            a = (int(line.start[0] * width), int(line.start[1] * height))
            b = (int(line.end[0] * width), int(line.end[1] * height))
            # The arrow points to the IN side: the right-hand side of A->B on screen.
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy) or 1.0
            mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
            tip = (int(mid[0] - dy / length * 35), int(mid[1] + dx / length * 35))
            line_pixels.append((line, a, b, mid, tip))

        return cls(
            size=(width, height),
            zones=zone_pixels,
            lines=line_pixels,
            fill_roi=roi,
            fill_layer=layer[roi].copy() if roi else None,
            fill_mask=mask[roi].copy() if roi else None,
        )


class FrameAnnotator:
    def __init__(self, scene: SceneConfig, tz: tzinfo) -> None:
        self._camera = scene.camera
        self._tz = tz
        self._zones = [z for z in scene.zones if z.enabled]
        self._lines = [ln for ln in scene.lines if ln.enabled]
        self._restricted = {z.id for z in self._zones if z.type is ZoneType.RESTRICTED}
        self._layout: _Layout | None = None

    def draw(
        self, image: np.ndarray, analysis: FrameAnalysis, alerts: Sequence[Alert] = ()
    ) -> np.ndarray:
        out = image.copy()
        h, w = out.shape[:2]
        if self._layout is None or self._layout.size != (w, h):
            self._layout = _Layout.build(self._zones, self._lines, w, h)
        scale = max(0.45, w / 1400)
        snapshot = analysis.snapshot

        self._draw_zones(out, self._layout, snapshot.zone_occupancy, scale)
        self._draw_lines(out, self._layout, snapshot.line_counts, scale)
        for track in snapshot.tracks:
            self._draw_track(out, track, scale)
        self._draw_hud(out, analysis, len(alerts), scale)
        if alerts and analysis.frame.timestamp_s - alerts[-1].stream_time_s <= _BANNER_SECONDS:
            self._draw_banner(out, alerts[-1], scale)
        return out

    def _draw_zones(
        self, out: np.ndarray, layout: _Layout, occupancy: dict[str, int], scale: float
    ) -> None:
        if layout.fill_roi is not None:
            region = out[layout.fill_roi]
            blended = cv2.addWeighted(
                region, 1 - _ZONE_OPACITY, layout.fill_layer, _ZONE_OPACITY, 0
            )
            cv2.copyTo(blended, layout.fill_mask, region)  # writes into `out` in place
        for zone, pts in layout.zones:
            color = _zone_color(zone)
            cv2.polylines(out, [pts], True, color, 2)
            corner = min(pts, key=lambda p: int(p[0]) + int(p[1]))  # top-left-most vertex
            text = f"{zone.name} [{zone.type.value}] inside: {occupancy.get(zone.id, 0)}"
            _label(out, text, (int(corner[0]), int(corner[1]) - 6), color, scale)

    def _draw_lines(
        self, out: np.ndarray, layout: _Layout, counts: dict[str, tuple[int, int]], scale: float
    ) -> None:
        for line, a, b, mid, tip in layout.lines:
            cv2.line(out, a, b, _YELLOW, 2)
            cv2.arrowedLine(out, mid, tip, _YELLOW, 2, tipLength=0.4)
            n_in, n_out = counts.get(line.id, (0, 0))
            _label(out, f"{line.name}  IN {n_in} | OUT {n_out}", (tip[0] + 6, tip[1]), _YELLOW,
                   scale)

    def _draw_track(self, out: np.ndarray, track: TrackState, scale: float) -> None:
        b = track.bbox
        p1, p2 = (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2))
        in_restricted = not self._restricted.isdisjoint(track.zone_ids)
        color = _RED if in_restricted else _class_color(track.object_class)
        cv2.rectangle(out, p1, p2, color, 2)
        label = f"{track.object_class} #{track.track_id} {track.confidence:.0%}"
        _label(out, label, (p1[0], p1[1] - 4), color, scale)
        h, w = out.shape[:2]
        foot = (int(track.position[0] * w), int(track.position[1] * h))
        cv2.circle(out, foot, 3, color, -1)

    def _draw_hud(
        self, out: np.ndarray, analysis: FrameAnalysis, alert_count: int, scale: float
    ) -> None:
        snapshot, frame, camera = analysis.snapshot, analysis.frame, self._camera
        others = [f"{cls} {n}" for cls, n in snapshot.current_counts.most_common()
                  if cls != "person"]
        minutes, seconds = divmod(frame.timestamp_s, 60)
        lines = [
            f"{camera.name}  |  {camera.location}" if camera.location else camera.name,
            frame.captured_at.astimezone(self._tz).strftime("%d %b %Y %H:%M:%S")
            + f"   video {int(minutes):02d}:{seconds:04.1f}",
            f"People now: {snapshot.current_counts['person']}"
            f"   Unique people: {snapshot.unique_counts.get('person', 0)}",
            "Objects now: " + (", ".join(others[:4]) if others else "none"),
        ]
        for line in self._lines:
            n_in, n_out = snapshot.line_counts.get(line.id, (0, 0))
            lines.append(f"{line.name}: IN {n_in}  OUT {n_out}")
        lines.append(f"Alerts: {alert_count}")

        font_scale = 0.5 * scale + 0.1
        line_h = int(26 * scale + 8)
        box_w = max(cv2.getTextSize(t, _FONT, font_scale, 1)[0][0] for t in lines) + 20
        top = 8
        region = out[top : top + line_h * len(lines) + 10, 8 : 8 + box_w]
        region //= 3  # darken the panel behind the text
        for i, text in enumerate(lines):
            y = top + 8 + line_h * (i + 1) - 6
            weight = 2 if i == 2 else 1  # people count in bold
            cv2.putText(out, text, (18, y), _FONT, font_scale, _WHITE, weight, cv2.LINE_AA)

    def _draw_banner(self, out: np.ndarray, alert: Alert, scale: float) -> None:
        h, w = out.shape[:2]
        bar_h = int(34 * scale + 14)
        cv2.rectangle(out, (0, h - bar_h), (w, h), _SEVERITY_COLORS.get(alert.severity, _RED), -1)
        where = alert.event.zone_name or self._camera.name
        sms = "  |  SMS sent" if alert.notify_sms else ""
        text = f"ALERT [{alert.severity.value}] {alert.event.title} - {where}{sms}"
        cv2.putText(out, text, (12, h - bar_h // 2 + 6), _FONT, 0.6 * scale + 0.1, _WHITE, 2,
                    cv2.LINE_AA)


def _label(img: np.ndarray, text: str, origin: Pixel, color: Color, scale: float) -> None:
    font_scale = 0.45 * scale + 0.05
    (tw, th), baseline = cv2.getTextSize(text, _FONT, font_scale, 1)
    x = max(0, min(origin[0], img.shape[1] - tw - 4))
    y = max(th + 4, origin[1])
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + baseline - 2), color, -1)
    cv2.putText(img, text, (x + 2, y - 2), _FONT, font_scale, _BLACK, 1, cv2.LINE_AA)
