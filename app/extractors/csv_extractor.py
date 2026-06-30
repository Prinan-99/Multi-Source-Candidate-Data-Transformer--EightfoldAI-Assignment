"""
Structured source extractor: Recruiter CSV.

Expected columns (case-insensitive, extras ignored):
  name / full_name, email, phone, company / current_company,
  title / job_title, location, linkedin, github, skills, headline

Missing columns or empty cells degrade gracefully — they become None, never
raise an exception.
"""

from __future__ import annotations
import csv
import io
import re
import uuid
from pathlib import Path
from typing import Any

from app.schema import FieldValue, RawExtraction
from app.normalizers.phone import to_e164
from app.normalizers.location import parse_location
from app.normalizers.skills import canonicalise_skill

SOURCE = "recruiter_csv"
BASE_CONFIDENCE = 0.85  # Human-entered structured data; reliable but can have typos


def _col(row: dict[str, str], *keys: str) -> str | None:
    """Case-insensitive key lookup; returns stripped value or None."""
    for k in keys:
        for col, val in row.items():
            if col.strip().lower().replace(" ", "_") == k.lower():
                v = val.strip() if val else ""
                return v if v else None
    return None


def _fv(value: Any, method: str = "direct", confidence: float = BASE_CONFIDENCE) -> FieldValue:
    return FieldValue(value=value, source=SOURCE, method=method, confidence=confidence)


def extract_from_csv(path: str | Path) -> list[RawExtraction]:
    """
    Parse a recruiter CSV and return one RawExtraction per row.
    Robust: skips unparseable rows, never raises for missing fields.
    """
    results: list[RawExtraction] = []
    path = Path(path)

    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        # Unreadable file → return empty list; pipeline continues with other sources
        print(f"[csv_extractor] Cannot read {path}: {exc}")
        return []

    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        try:
            extraction = _parse_row(row)
            results.append(extraction)
        except Exception as exc:
            print(f"[csv_extractor] Skipping row due to error: {exc}")

    return results


def _parse_row(row: dict[str, str]) -> RawExtraction:
    ext = RawExtraction(source_name=SOURCE)

    # Name
    name = _col(row, "name", "full_name", "candidate_name")
    if name:
        ext.full_name = _fv(name)

    # Emails
    email = _col(row, "email", "email_address", "e-mail")
    if email:
        # Some cells have comma-separated emails
        for addr in re.split(r"[;,\s]+", email):
            addr = addr.strip().lower()
            if "@" in addr:
                ext.emails.append(_fv(addr))

    # Phones
    phone = _col(row, "phone", "phone_number", "mobile", "contact")
    if phone:
        normalised = to_e164(phone)
        ext.phones.append(_fv(
            normalised if normalised else phone,
            confidence=BASE_CONFIDENCE if normalised else 0.5,
        ))

    # Location
    location_raw = _col(row, "location", "city", "address")
    if location_raw:
        ext.location = _fv(parse_location(location_raw), method="parsed")

    # Links
    links: dict[str, Any] = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    linkedin = _col(row, "linkedin", "linkedin_url", "linkedin_profile")
    if linkedin:
        links["linkedin"] = linkedin
    github = _col(row, "github", "github_url", "github_profile")
    if github:
        links["github"] = github
    if any(v for v in links.values() if v):
        ext.links = _fv(links)

    # Headline / title
    headline = _col(row, "headline", "title", "job_title", "current_title")
    company = _col(row, "company", "current_company", "employer")
    if headline and company:
        ext.headline = _fv(f"{headline} at {company}")
    elif headline:
        ext.headline = _fv(headline)
    elif company:
        ext.headline = _fv(company, confidence=0.6)

    # Experience (single entry from CSV)
    if company or headline:
        exp: dict[str, Any] = {
            "company": company or "Unknown",
            "title": headline,
            "start": None,
            "end": None,
            "summary": None,
        }
        ext.experience.append(_fv(exp, confidence=0.80))

    # Skills (comma-separated in a "skills" column)
    skills_raw = _col(row, "skills", "skill", "technologies", "tech_stack")
    if skills_raw:
        for s in re.split(r"[,;|/]+", skills_raw):
            s = s.strip()
            if s:
                ext.skills.append(_fv(
                    {"name": canonicalise_skill(s), "confidence": BASE_CONFIDENCE},
                    method="direct",
                ))

    return ext
