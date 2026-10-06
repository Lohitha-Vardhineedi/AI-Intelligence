from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.events.types import Severity


@dataclass(frozen=True, slots=True)
class AlertMessage:
    severity: Severity
    camera_name: str
    location: str
    event_title: str
    occurred_at: datetime  # already converted to local time

    @property
    def time_text(self) -> str:
        return self.occurred_at.strftime("%I:%M %p").lstrip("0")

    def variables(self) -> dict[str, str]:
        """Variables for template-based providers such as MSG91 (DLT templates)."""
        return {
            "severity": self.severity.value,
            "camera": self.camera_name,
            "location": self.location,
            "event": self.event_title,
            "time": self.time_text,
        }


def render_alert_sms(message: AlertMessage) -> str:
    lines = ["AI Surveillance Alert"]
    if message.severity is Severity.CRITICAL:
        lines += [f"Severity: {message.severity.value}"]
    lines += ["", f"Camera: {message.camera_name}"]
    if message.location:
        lines += [f"Location: {message.location}"]
    lines += [
        "",
        f"Event: {message.event_title}",
        f"Time: {message.time_text}",
        "",
        "Please check the surveillance dashboard.",
    ]
    return "\n".join(lines)
