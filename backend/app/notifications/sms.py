"""SMS provider interface. The provider is chosen with SMS_PROVIDER in .env."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.config import Settings


class SMSConfigurationError(RuntimeError):
    """The selected provider is missing configuration (e.g. credentials)."""


@dataclass(frozen=True, slots=True)
class SMSResult:
    success: bool
    provider: str
    message_id: str | None = None
    error: str | None = None
    retryable: bool = False  # temporary failure (network, rate limit, 5xx)


class SMSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send_sms(
        self, phone_number: str, message: str, variables: Mapping[str, str] | None = None
    ) -> SMSResult:
        """Send `message` to `phone_number` (E.164).

        `variables` carries the template fields for template-based providers.
        """


def create_sms_provider(settings: Settings) -> SMSProvider:
    provider = settings.sms_provider
    if provider == "console":
        from app.notifications.providers.console import ConsoleSMSProvider

        return ConsoleSMSProvider()
    if provider == "twilio":
        from app.notifications.providers.twilio import TwilioSMSProvider

        return TwilioSMSProvider(
            account_sid=settings.sms_account_sid,
            auth_token=settings.sms_auth_token.get_secret_value(),
            from_number=settings.sms_from_number,
        )
    if provider == "msg91":
        from app.notifications.providers.msg91 import Msg91SMSProvider

        return Msg91SMSProvider(
            auth_key=settings.sms_api_key.get_secret_value(),
            template_id=settings.sms_template_id,
        )
    if provider == "aws_sns":
        from app.notifications.providers.aws_sns import AwsSnsSMSProvider

        return AwsSnsSMSProvider(
            region=settings.aws_region,
            sender_id=settings.sms_sender_id,
            dlt_entity_id=settings.sms_dlt_entity_id,
            dlt_template_id=settings.sms_dlt_template_id,
        )
    raise SMSConfigurationError(f"Unknown SMS_PROVIDER: {provider}")
