"""Sends SMS on worker threads (a slow SMS API never stalls the video), with retries
and a per-recipient hourly limit."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.notifications.phone import mask_phone_number, normalize_phone_number
from app.notifications.sms import SMSProvider, SMSResult

logger = logging.getLogger(__name__)

_RATE_WINDOW_S = 3600.0


class NotificationStatus(StrEnum):
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"  # blocked by the per-recipient rate limit


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    alert_id: str
    provider: str
    to_masked: str
    status: NotificationStatus
    attempts: int
    message_id: str | None
    error: str | None
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "alert_id": self.alert_id,
            "provider": self.provider,
            "to": self.to_masked,
            "status": self.status.value,
            "attempts": self.attempts,
            "message_id": self.message_id,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


class NotificationManager:
    def __init__(
        self,
        provider: SMSProvider,
        default_recipients: Sequence[str],
        *,
        default_country_code: str = "91",
        max_per_hour: int = 10,
        max_attempts: int = 3,
        retry_backoff_s: float = 1.0,
        workers: int = 2,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._provider = provider
        self._country_code = default_country_code
        self._default = [self._normalize(n) for n in default_recipients]
        self._max_per_hour = max_per_hour
        self._max_attempts = max_attempts
        self._backoff_s = retry_backoff_s
        self._clock = clock
        self._sleep = sleep
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sms")
        self._lock = threading.Lock()
        self._sent_at: defaultdict[str, deque[float]] = defaultdict(deque)
        self._records: list[NotificationRecord] = []

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def default_recipients(self) -> list[str]:
        return list(self._default)

    @property
    def records(self) -> list[NotificationRecord]:
        with self._lock:
            return list(self._records)

    def _normalize(self, number: str) -> str:
        return normalize_phone_number(number, self._country_code)

    def send_alert(
        self,
        alert_id: str,
        message: str,
        *,
        recipients: Sequence[str] | None = None,
        variables: Mapping[str, str] | None = None,
    ) -> list[Future[NotificationRecord]]:
        targets = [self._normalize(n) for n in recipients] if recipients else self._default
        if not targets:
            logger.warning("Alert has SMS enabled but no recipients are configured",
                           extra={"alert_id": alert_id})
        futures: list[Future[NotificationRecord]] = []
        for number in targets:
            if not self._reserve_slot(number):
                self._record(alert_id, number, NotificationStatus.SUPPRESSED, 0, None,
                             f"rate limit of {self._max_per_hour} SMS/hour reached")
                continue
            futures.append(self._executor.submit(self._deliver, alert_id, number, message,
                                                 variables))
        return futures

    def close(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _reserve_slot(self, number: str) -> bool:
        now = self._clock()
        with self._lock:
            sent = self._sent_at[number]
            while sent and now - sent[0] > _RATE_WINDOW_S:
                sent.popleft()
            if len(sent) >= self._max_per_hour:
                return False
            sent.append(now)
            return True

    def _deliver(
        self, alert_id: str, number: str, message: str, variables: Mapping[str, str] | None
    ) -> NotificationRecord:
        result = SMSResult(False, self._provider.name, error="not attempted")
        attempts = 0
        while attempts < self._max_attempts:
            attempts += 1
            try:
                result = self._provider.send_sms(number, message, variables)
            except Exception as exc:  # a buggy provider must not kill the worker thread
                logger.exception("SMS provider raised an exception")
                result = SMSResult(False, self._provider.name, error=str(exc))
            if result.success or not result.retryable:
                break
            if attempts < self._max_attempts:
                self._sleep(self._backoff_s * 2 ** (attempts - 1))

        status = NotificationStatus.SENT if result.success else NotificationStatus.FAILED
        return self._record(alert_id, number, status, attempts, result.message_id, result.error)

    def _record(
        self,
        alert_id: str,
        number: str,
        status: NotificationStatus,
        attempts: int,
        message_id: str | None,
        error: str | None,
    ) -> NotificationRecord:
        record = NotificationRecord(
            alert_id=alert_id,
            provider=self._provider.name,
            to_masked=mask_phone_number(number),
            status=status,
            attempts=attempts,
            message_id=message_id,
            error=error,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._records.append(record)
        log = logger.info if status is NotificationStatus.SENT else logger.error
        log("SMS %s to %s via %s", status.value, record.to_masked, record.provider,
            extra={"alert_id": alert_id, **({"error": error} if error else {})})
        return record
