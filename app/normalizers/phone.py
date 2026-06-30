"""Normalise phone numbers to E.164 format (+15551234567)."""

from __future__ import annotations
import re
import phonenumbers


def to_e164(raw: str, default_region: str = "US") -> str | None:
    """
    Parse and format a phone number as E.164.
    Returns None if the number cannot be parsed or is invalid.
    Never raises.
    """
    if not raw or not isinstance(raw, str):
        return None

    raw = raw.strip()
    if not raw:
        return None

    try:
        parsed = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass

    # Try stripping common non-digit clutter and retry
    digits_only = re.sub(r"[^\d+]", "", raw)
    if digits_only:
        try:
            parsed = phonenumbers.parse(digits_only, default_region)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            pass

    return None


def normalise_phones(raw_list: list[str], default_region: str = "US") -> list[str]:
    """Normalise a list of raw strings; return only valid E.164 values, deduplicated."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_list:
        normalised = to_e164(raw, default_region)
        if normalised and normalised not in seen:
            seen.add(normalised)
            result.append(normalised)
    return result
