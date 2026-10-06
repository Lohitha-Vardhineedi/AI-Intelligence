"""AWS SNS. Needs `pip install boto3` and the standard AWS credentials."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.notifications.sms import SMSConfigurationError, SMSProvider, SMSResult

_RETRYABLE_CODES = {"Throttling", "ThrottlingException", "InternalError", "InternalFailure",
                    "ServiceUnavailable"}


class AwsSnsSMSProvider(SMSProvider):
    name = "aws_sns"

    def __init__(
        self,
        *,
        region: str,
        sender_id: str = "",
        dlt_entity_id: str = "",
        dlt_template_id: str = "",
    ) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise SMSConfigurationError("AWS SNS needs boto3: pip install boto3") from exc
        self._client = boto3.client("sns", region_name=region)
        self._attributes: dict[str, Any] = {
            "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
        }
        # India: SNS requires the DLT entity and template IDs for business SMS.
        for key, value in (
            ("AWS.SNS.SMS.SenderID", sender_id),
            ("AWS.MM.SMS.EntityId", dlt_entity_id),
            ("AWS.MM.SMS.TemplateId", dlt_template_id),
        ):
            if value:
                self._attributes[key] = {"DataType": "String", "StringValue": value}

    def send_sms(
        self, phone_number: str, message: str, variables: Mapping[str, str] | None = None
    ) -> SMSResult:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            response = self._client.publish(
                PhoneNumber=phone_number, Message=message, MessageAttributes=self._attributes
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            return SMSResult(False, self.name, error=f"{code}: {exc}",
                             retryable=code in _RETRYABLE_CODES)
        except BotoCoreError as exc:
            return SMSResult(False, self.name, error=str(exc), retryable=True)
        return SMSResult(True, self.name, message_id=response.get("MessageId"))
