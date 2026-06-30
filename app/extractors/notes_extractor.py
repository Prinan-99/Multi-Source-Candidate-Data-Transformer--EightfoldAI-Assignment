"""
Unstructured source extractor: Recruiter notes (.txt free text).

Reuses the same regex helpers from resume_extractor.
Confidence is 0.60 — recruiter prose is the least reliable source.
Only extracts: name, emails, phones, LinkedIn/GitHub links, location.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

from app.schema import FieldValue, RawExtraction
from app.normalizers.phone import to_e164
from app.normalizers.location import parse_location
from app.extractors.resume_extractor import (
    _EMAIL_RE, _PHONE_RE, _LINKEDIN_RE, _GITHUB_RE,
)

SOURCE = "recruiter_notes"
BASE_CONFIDENCE = 0.60


def _fv(value: Any, method: str = "regex") -> FieldValue:
    return FieldValue(value=value, source=SOURCE, method=method, confidence=BASE_CONFIDENCE)


def extract_from_notes(path: str | Path) -> RawExtraction:
    """
    Parse a recruiter notes .txt file and return a RawExtraction.
    Never raises — unreadable file returns an empty extraction.
    """
    ext = RawExtraction(source_name=SOURCE)
    path = Path(path)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"[notes_extractor] Cannot read {path}: {exc}")
        return ext

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ext

    import re
    _URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
    # Labels like "Candidate: Jane Doe" or "Name: Jane Doe"
    _LABEL_RE = re.compile(r"^(candidate|name|applicant)\s*:\s*", re.IGNORECASE)

    # Name: first short line that isn't an email/phone/URL
    for line in lines[:6]:
        clean = _LABEL_RE.sub("", line).strip()
        if (
            not _EMAIL_RE.search(clean)
            and not _PHONE_RE.search(clean)
            and not _URL_RE.search(clean)
            and 2 <= len(clean.split()) <= 6
        ):
            ext.full_name = _fv(clean, method="first_line")
            break

    # Emails
    for addr in _EMAIL_RE.findall(text):
        ext.emails.append(_fv(addr.strip().lower()))

    # Phones
    seen: set[str] = set()
    for raw in _PHONE_RE.findall(text):
        normalised = to_e164(raw)
        target = normalised if normalised else raw
        if target not in seen:
            seen.add(target)
            ext.phones.append(_fv(target))

    # LinkedIn / GitHub links
    links: dict[str, Any] = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    m = _LINKEDIN_RE.search(text)
    if m:
        links["linkedin"] = f"https://linkedin.com/in/{m.group(1)}"
    m2 = _GITHUB_RE.search(text)
    if m2:
        links["github"] = f"https://github.com/{m2.group(1)}"
    if links["linkedin"] or links["github"]:
        ext.links = _fv(links, method="regex_url")

    # Location: look for "City, Country" pattern, strip label prefix
    _LOC_LABEL_RE = re.compile(r"^(location|city|address)\s*:\s*", re.IGNORECASE)
    for line in lines[:12]:
        clean_line = _LOC_LABEL_RE.sub("", line).strip()
        if re.search(r",\s*[A-Za-z]{2,}", clean_line) and not _EMAIL_RE.search(clean_line):
            loc = parse_location(clean_line)
            if loc.get("country") or loc.get("city"):
                ext.location = _fv(loc, method="regex_location")
                break

    return ext
