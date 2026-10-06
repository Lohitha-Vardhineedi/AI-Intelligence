from datetime import UTC, datetime, timedelta

import pytest

from app.events.processor import EventProcessor
from app.events.rules import RuleEngine
from app.events.types import Event, EventType, Severity
from app.notifications.manager import NotificationManager
from app.schemas.scene import ScheduleConfig, Weekday
from tests.helpers import T0, FakeSMSProvider, scene


def _event(t: float, *, track_id: int = 1, zone: str = "room", cls: str = "person",
           event_type: EventType = EventType.INTRUSION_DETECTED, conf: float = 0.9) -> Event:
    return Event(
        event_type=event_type, severity=Severity.HIGH, camera_id="cam-1",
        occurred_at=T0 + timedelta(seconds=t), stream_time_s=t, frame_index=int(t * 10),
        track_id=track_id, object_class=cls, confidence=conf, zone_id=zone,
        zone_name="Room 101",
    )


def test_rule_matches_on_event_type_zone_and_class():
    engine = RuleEngine(scene().rules, UTC)
    assert engine.match(_event(0))
    assert not engine.match(_event(0, zone="other"))
    assert not engine.match(_event(0, cls="dog"))
    assert not engine.match(_event(0, event_type=EventType.ZONE_ENTERED))


def test_schedule_supports_overnight_windows():
    night = ScheduleConfig(days=[Weekday.MON], start="22:00", end="06:00")
    monday_23 = datetime(2026, 10, 5, 23, 0)  # 5 Oct 2026 is a Monday
    assert night.is_active(monday_23)
    assert night.is_active(monday_23 + timedelta(hours=4))  # Tue 03:00 belongs to Monday
    assert not night.is_active(monday_23 + timedelta(hours=10))
    assert not night.is_active(monday_23 + timedelta(days=1))  # Tuesday 23:00


@pytest.fixture
def processing():
    provider = FakeSMSProvider()
    notifier = NotificationManager(provider, ["9876543210"], sleep=lambda _: None)
    config = scene()
    processor = EventProcessor(rule_engine=RuleEngine(config.rules, UTC), camera=config.camera,
                               tz=UTC, notifier=notifier)
    yield processor, notifier, provider
    notifier.close()


def test_twenty_intrusions_within_cooldown_send_one_sms(processing):
    processor, notifier, provider = processing
    for i in range(20):  # 20 events in 20 s - different track IDs, same zone
        processor.handle(_event(float(i), track_id=i))
    notifier.close(wait=True)
    assert len(processor.alerts) == 1
    assert processor.alerts[0].occurrence_count == 20
    assert len(provider.sent) == 1
    number, message = provider.sent[0]
    assert number == "+919876543210"
    assert "Severity: CRITICAL" in message
    assert "Event: Unauthorized Person Entry" in message


def test_new_alert_after_cooldown_expires(processing):
    processor, notifier, provider = processing
    processor.handle(_event(0))
    processor.handle(_event(30))
    processor.handle(_event(61))
    notifier.close(wait=True)
    assert len(processor.alerts) == 2
    assert len(provider.sent) == 2
