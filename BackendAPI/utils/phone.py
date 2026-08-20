"""Kenyan mobile numbers, and which of them can take an M-Pesa prompt.

M-Pesa is Safaricom's. An STK push to an Airtel or Telkom line does not arrive,
so a number on another network is not a payment method — accepting one defers
the failure to the moment a customer is trying to pay.

The prefix table is the mechanism, and it is the part that ages: Kenya's
regulator reassigns ranges from time to time. It lives here, once, so a
reassignment is one edit rather than a hunt.
"""
from __future__ import annotations

import re

#: National significant prefixes allocated to Safaricom, as (low, high)
#: inclusive ranges over the first three digits of the nine-digit national
#: number (so `0712345678` and `+254712345678` both reduce to `712`).
#:
#: Airtel (`730-739`, `750-756`, `762`, `780-789`, `100-106`) and Telkom
#: (`770-779`) are deliberately absent.
SAFARICOM_PREFIX_RANGES: tuple[tuple[int, int], ...] = (
    (110, 115),
    (700, 729),
    (740, 743),
    (745, 746),
    (748, 748),
    (757, 759),
    (768, 769),
    (790, 799),
)

_NATIONAL = re.compile(r"^[17]\d{8}$")


def national(raw: str | None) -> str | None:
    """Nine digits, no country code and no leading zero, or None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("254"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits or None


def is_kenyan_mobile(raw: str | None) -> bool:
    """A well-formed Kenyan mobile number on any network."""
    value = national(raw)
    return bool(value and _NATIONAL.match(value))


def is_safaricom(raw: str | None) -> bool:
    """A Safaricom line — the only kind that can receive an M-Pesa prompt."""
    value = national(raw)
    if not value or not _NATIONAL.match(value):
        return False
    prefix = int(value[:3])
    return any(low <= prefix <= high for low, high in SAFARICOM_PREFIX_RANGES)


def to_e164(raw: str | None) -> str | None:
    """The canonical stored form, `+254XXXXXXXXX`."""
    value = national(raw)
    return f"+254{value}" if value else None
