"""Event -> matching rules -> alert (with cooldown) -> snapshot and SMS."""

from __future__ import annotations

import logging
from datetime import tzinfo
from typing import Protocol

import numpy as np

from app.events.rules import RuleEngine
from app.events.types import Alert, Event, EventType
from app.notifications.manager import NotificationManager
from app.notifications.templates import AlertMessage, render_alert_sms
from app.schemas.scene import CameraConfig

logger = logging.getLogger(__name__)

# These always get an evidence image, even when no rule matches.
SNAPSHOT_EVENT_TYPES = frozenset({
    EventType.INTRUSION_DETECTED,
    EventType.LOITERING_DETECTED,
    EventType.CROWD_DETECTED,
    EventType.OBJECT_COUNT_THRESHOLD,
})


class SnapshotSaver(Protocol):
    def save(self, event: Event, image: np.ndarray) -> str: ...


class EventProcessor:
    def __init__(
        self,
        *,
        rule_engine: RuleEngine,
        camera: CameraConfig,
        tz: tzinfo,
        notifier: NotificationManager | None = None,
        snapshots: SnapshotSaver | None = None,
    ) -> None:
        self._rules = rule_engine
        self._camera = camera
        self._tz = tz
        self._notifier = notifier
        self._snapshots = snapshots
        self._open_alerts: dict[str, Alert] = {}  # dedup key -> latest alert
        self.alerts: list[Alert] = []

    def handle(self, event: Event, image: np.ndarray | None = None) -> list[Alert]:
        if image is not None and event.event_type in SNAPSHOT_EVENT_TYPES:
            self._save_snapshot(event, image)

        created: list[Alert] = []
        for rule in self._rules.match(event):
            key = RuleEngine.dedup_key(rule, event)
            previous = self._open_alerts.get(key)
            if previous and event.stream_time_s - previous.stream_time_s < rule.cooldown_seconds:
                previous.occurrence_count += 1
                previous.last_occurred_at = event.occurred_at
                continue

            if rule.actions.snapshot and image is not None:
                self._save_snapshot(event, image)
            alert = Alert(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity or event.severity,
                event=event,
                created_at=event.occurred_at,
                stream_time_s=event.stream_time_s,
                notify_sms=rule.actions.sms,
            )
            self._open_alerts[key] = alert
            self.alerts.append(alert)
            created.append(alert)
            logger.warning(
                "ALERT [%s] %s - %s",
                alert.severity.value,
                event.title,
                event.zone_name or self._camera.name,
                extra={"alert_id": alert.alert_id, "track_id": event.track_id},
            )
            if rule.actions.sms and self._notifier is not None:
                self._send_sms(alert, rule.recipients)
        return created

    def _save_snapshot(self, event: Event, image: np.ndarray) -> None:
        if self._snapshots is not None and event.snapshot_path is None:
            event.snapshot_path = self._snapshots.save(event, image)

    def _send_sms(self, alert: Alert, recipients: list[str]) -> None:
        assert self._notifier is not None
        event = alert.event
        message = AlertMessage(
            severity=alert.severity,
            camera_name=self._camera.name,
            location=self._camera.location or event.zone_name or "",
            event_title=event.title,
            occurred_at=event.occurred_at.astimezone(self._tz),
        )
        self._notifier.send_alert(
            alert.alert_id,
            render_alert_sms(message),
            recipients=recipients or None,
            variables=message.variables(),
        )
