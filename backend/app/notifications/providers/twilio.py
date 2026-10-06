"""Twilio Messaging over its REST API, so the Twilio SDK isn't needed."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from app.notifications.sms import SMSConfigurationError, SMSProvider, SMSResult

_API_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class TwilioSMSProvider(SMSProvider):
    name = "twilio"

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        timeout_s: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("SMS_ACCOUNT_SID", account_sid),
                ("SMS_AUTH_TOKEN", auth_token),
                ("SMS_FROM_NUMBER", from_number),
            )
            if not value
        ]
        if missing:
            raise SMSConfigurationError(
                f"Twilio needs these settings in .env: {', '.join(missing)}"
            )
        self._url = _API_URL.format(sid=account_sid)
        self._auth = (account_sid, auth_token)
        # A Messaging Service SID (MG...) can be used instead of a phone number.
        self._sender_field = "MessagingServiceSid" if from_number.startswith("MG") else "From"
        self._from = from_number
        self._client = client or httpx.Client(timeout=timeout_s)

    def send_sms(
        self, phone_number: str, message: str, variables: Mapping[str, str] | None = None
    ) -> SMSResult:
        data = {"To": phone_number, self._sender_field: self._from, "Body": message}
        try:
            response = self._client.post(self._url, data=data, auth=self._auth)
        except httpx.HTTPError as exc:
            return SMSResult(False, self.name, error=f"network error: {type(exc).__name__}",
                             retryable=True)
        if response.status_code in (200, 201):
            return SMSResult(True, self.name, message_id=response.json().get("sid"))
        try:
            body = response.json()
            detail = f"{body.get('code')}: {body.get('message')}"
        except ValueError:
            detail = response.text[:200]
        return SMSResult(
            False,
            self.name,
            error=f"HTTP {response.status_code} - {detail}",
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
