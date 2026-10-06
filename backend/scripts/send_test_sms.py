"""Send one test SMS through the configured provider, to check your .env settings.

    python -m scripts.send_test_sms                 # to SMS_RECIPIENTS
    python -m scripts.send_test_sms --to 98XXXXXXXX
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.events.types import Severity
from app.notifications.manager import NotificationManager, NotificationStatus
from app.notifications.sms import create_sms_provider
from app.notifications.templates import AlertMessage, render_alert_sms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a test SMS")
    parser.add_argument("--to", action="append", help="recipient (repeatable)")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        manager = NotificationManager(
            create_sms_provider(settings),
            settings.recipients,
            default_country_code=settings.sms_default_country_code,
        )
    except Exception as exc:
        print(f"SMS configuration error: {exc}")
        return 2

    message = AlertMessage(
        severity=Severity.INFO,
        camera_name="Test Camera",
        location="Test",
        event_title="Test message - SMS alerts are working",
        occurred_at=datetime.now(settings.tz),
    )
    futures = manager.send_alert(
        "test", render_alert_sms(message), recipients=args.to, variables=message.variables()
    )
    if not futures:
        print("No recipients. Set SMS_RECIPIENTS in .env or pass --to.")
        return 2
    records = [f.result() for f in futures]
    manager.close()
    for record in records:
        detail = record.message_id if record.status is NotificationStatus.SENT else record.error
        print(f"{record.status.value}: {record.to_masked} via {record.provider} - {detail}")
    return 0 if all(r.status is NotificationStatus.SENT for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
