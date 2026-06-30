"""Normalise date strings to YYYY-MM format."""

from __future__ import annotations
import re
from datetime import datetime


_MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# Matches: "Jan 2021", "January 2021", "2021-01", "01/2021", "2021"
_PATTERNS = [
    (re.compile(r"(\d{4})[/-](\d{1,2})"), lambda m: f"{m.group(1)}-{int(m.group(2)):02d}"),
    (re.compile(r"(\d{1,2})[/-](\d{4})"), lambda m: f"{m.group(2)}-{int(m.group(1)):02d}"),
    (re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{4})"), lambda m: (
        f"{m.group(2)}-{_MONTH_MAP.get(m.group(1)[:3].lower(), '01')}"
    )),
    (re.compile(r"(\d{4})$"), lambda m: f"{m.group(1)}-01"),
]


def to_year_month(raw: str | None) -> str | None:
    """
    Parse a variety of date formats and return YYYY-MM.
    Returns None if the string cannot be interpreted.
    "present", "current", "now" → returns "present".
    """
    if not raw:
        return None

    clean = raw.strip()
    if clean.lower() in {"present", "current", "now", "ongoing"}:
        return "present"

    for pattern, formatter in _PATTERNS:
        m = pattern.search(clean)
        if m:
            result = formatter(m)
            # Sanity check: month must be 01-12
            parts = result.split("-")
            if len(parts) == 2 and 1 <= int(parts[1]) <= 12:
                return result

    return None


def years_between(start: str | None, end: str | None) -> float | None:
    """Compute approximate years between two YYYY-MM strings (or 'present')."""
    if not start:
        return None
    end_resolved = end if end and end != "present" else datetime.now().strftime("%Y-%m")
    try:
        s = datetime.strptime(start, "%Y-%m")
        e = datetime.strptime(end_resolved, "%Y-%m")
        return max(0.0, round((e - s).days / 365.25, 1))
    except ValueError:
        return None
