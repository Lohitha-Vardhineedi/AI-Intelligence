from datetime import datetime

import pytest

from app.events.types import Severity
from app.notifications.manager import NotificationManager, NotificationStatus
from app.notifications.phone import (
    InvalidPhoneNumberError,
    mask_phone_number,
    normalize_phone_number,
)
from app.notifications.sms import SMSResult
from app.notifications.templates import AlertMessage, render_alert_sms
from app.security.url_guard import redact_url
from tests.helpers import FakeSMSProvider


@pytest.mark.parametrize(
    "raw",
    ["9381558756", "+919381558756", "919381558756", "09381558756", "+91 93815 58756",
     "0091-9381558756"],
)
def test_normalize_indian_numbers(raw):
    assert normalize_phone_number(raw) == "+919381558756"


@pytest.mark.parametrize("raw", ["12345", "abcdefghij", "+91123456789", "+915381558756"])
def test_invalid_numbers_rejected(raw):
    with pytest.raises(InvalidPhoneNumberError):
        normalize_phone_number(raw)


def test_international_number_kept():
    assert normalize_phone_number("+14155550123") == "+14155550123"


def test_mask_phone_number():
    assert mask_phone_number("+919381558756") == "+91XXXXXX8756"


def test_redact_camera_url():
    url = "rtsp://admin:s3cret@192.168.1.20:554/stream1"
    assert redact_url(url) == "rtsp://***@192.168.1.20:554/stream1"


def test_sms_template_matches_brief_format():
    message = render_alert_sms(AlertMessage(
        severity=Severity.CRITICAL, camera_name="Camera 01", location="Room 101",
        event_title="Unauthorized Person Entry", occurred_at=datetime(2026, 10, 5, 10, 42),
    ))
    assert message.splitlines() == [
        "AI Surveillance Alert",
        "Severity: CRITICAL",
        "",
        "Camera: Camera 01",
        "Location: Room 101",
        "",
        "Event: Unauthorized Person Entry",
        "Time: 10:42 AM",
        "",
        "Please check the surveillance dashboard.",
    ]


def test_retries_temporary_failures_then_succeeds():
    provider = FakeSMSProvider([
        SMSResult(False, "fake", error="timeout", retryable=True),
        SMSResult(True, "fake", message_id="ok"),
    ])
    manager = NotificationManager(provider, ["9381558756"], sleep=lambda _: None)
    record = manager.send_alert("a1", "hello")[0].result()
    manager.close()
    assert record.status is NotificationStatus.SENT
    assert record.attempts == 2


def test_permanent_failure_is_not_retried():
    provider = FakeSMSProvider([SMSResult(False, "fake", error="invalid number")])
    manager = NotificationManager(provider, ["9381558756"], sleep=lambda _: None)
    record = manager.send_alert("a1", "hello")[0].result()
    manager.close()
    assert record.status is NotificationStatus.FAILED
    assert record.attempts == 1


def test_rate_limit_per_recipient():
    provider = FakeSMSProvider()
    manager = NotificationManager(provider, ["9381558756"], max_per_hour=2,
                                  sleep=lambda _: None)
    for i in range(4):
        manager.send_alert(f"a{i}", "hello")
    manager.close(wait=True)
    statuses = [r.status for r in manager.records]
    assert statuses.count(NotificationStatus.SENT) == 2
    assert statuses.count(NotificationStatus.SUPPRESSED) == 2
    assert len(provider.sent) == 2
