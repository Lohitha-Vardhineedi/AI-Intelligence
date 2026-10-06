"""Prints the SMS instead of sending it. For development and --dry-run."""

from __future__ import annotations

import sys
import threading
from collections.abc import Mapping
from typing import TextIO

from app.events.types import new_id
from app.notifications.phone import mask_phone_number
from app.notifications.sms import SMSProvider, SMSResult

_print_lock = threading.Lock()


class ConsoleSMSProvider(SMSProvider):
    name = "console"

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout

    def send_sms(
        self, phone_number: str, message: str, variables: Mapping[str, str] | None = None
    ) -> SMSResult:
        width = 58
        border = "+" + "-" * width + "+"
        header = f" SMS to {mask_phone_number(phone_number)} (console - not actually sent) "
        body = [f"| {line:<{width - 2}} |" for line in message.splitlines()]
        with _print_lock:
            print("\n" + "+" + header.center(width, "-") + "+", file=self._stream)
            print("\n".join(body), file=self._stream)
            print(border + "\n", file=self._stream, flush=True)
        return SMSResult(success=True, provider=self.name, message_id=f"console-{new_id()}")
