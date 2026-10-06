"""MSG91 Flow API. Business SMS in India must use a DLT-approved template; its variables
must be named severity, camera, location, event and time."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from app.notifications.sms import SMSConfigurationError, SMSProvider, SMSResult

_API_URL = "https://control.msg91.com/api/v5/flow"


class Msg91SMSProvider(SMSProvider):
    name = "msg91"

    def __init__(
        self,
        *,
        auth_key: str,
        template_id: str,
        timeout_s: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not auth_key or not template_id:
            raise SMSConfigurationError("MSG91 needs SMS_API_KEY and SMS_TEMPLATE_ID in .env")
        self._headers = {"authkey": auth_key, "accept": "application/json"}
        self._template_id = template_id
        self._client = client or httpx.Client(timeout=timeout_s)

    def send_sms(
        self, phone_number: str, message: str, variables: Mapping[str, str] | None = None
    ) -> SMSResult:
        recipient = {"mobiles": phone_number.lstrip("+"), **(variables or {"message": message})}
        payload = {"template_id": self._template_id, "short_url": "0", "recipients": [recipient]}
        try:
            response = self._client.post(_API_URL, json=payload, headers=self._headers)
        except httpx.HTTPError as exc:
            return SMSResult(False, self.name, error=f"network error: {type(exc).__name__}",
                             retryable=True)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200 and body.get("type") == "success":
            return SMSResult(True, self.name, message_id=str(body.get("message")))
        return SMSResult(
            False,
            self.name,
            error=f"HTTP {response.status_code} - {body.get('message') or response.text[:200]}",
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
