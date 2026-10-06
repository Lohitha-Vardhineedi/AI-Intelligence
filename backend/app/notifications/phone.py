"""Phone number normalisation (E.164) and masking for logs and the UI."""

from __future__ import annotations

import re

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_INDIA_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


class InvalidPhoneNumberError(ValueError):
    pass


def normalize_phone_number(raw: str, default_country_code: str = "91") -> str:
    """Return the number in E.164 format, e.g. "9876543210" -> "+919876543210"."""
    cleaned = re.sub(r"[\s\-().]", "", raw or "")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not cleaned.startswith("+"):
        if not cleaned.isdigit():
            raise InvalidPhoneNumberError(f"Invalid phone number: {mask_phone_number(raw)}")
        country = default_country_code.lstrip("+")
        digits = cleaned.lstrip("0")
        if len(digits) > 10 and digits.startswith(country):
            cleaned = "+" + digits
        else:
            cleaned = f"+{country}{digits}"
    if not _E164.match(cleaned) or (cleaned.startswith("+91") and not _INDIA_MOBILE.match(cleaned)):
        raise InvalidPhoneNumberError(f"Invalid phone number: {mask_phone_number(raw)}")
    return cleaned


def mask_phone_number(number: str) -> str:
    """"+919876543210" -> "+91XXXXXX3210". Never log full phone numbers."""
    number = (number or "").strip()
    if len(number) <= 4:
        return "X" * len(number)
    prefix = number[:3] if number.startswith("+") else ""
    return prefix + "X" * (len(number) - len(prefix) - 4) + number[-4:]
