"""
Unstructured source extractor: LinkedIn profile URL.

LinkedIn blocks direct scraping (HTTP 999, bot detection) and their ToS
prohibits it. Production implementation uses Proxycurl — a licensed LinkedIn
data API (~$0.01/profile) that returns structured JSON.

Set PROXYCURL_API_KEY in your environment to enable live fetching.
Without a key, the extractor logs a clear message and returns an empty
RawExtraction so the pipeline continues with other sources.

Proxycurl docs: https://nubela.co/proxycurl/docs
"""

from __future__ import annotations
import os
import re
from typing import Any

from app.schema import FieldValue, RawExtraction
from app.normalizers.phone import to_e164
from app.normalizers.location import parse_location
from app.normalizers.skills import canonicalise_skill
from app.normalizers.date import to_year_month

SOURCE = "linkedin_api"
BASE_CONFIDENCE = 0.88   # LinkedIn profile data is self-reported but rich


def _fv(value: Any, method: str = "api", confidence: float = BASE_CONFIDENCE) -> FieldValue:
    return FieldValue(value=value, source=SOURCE, method=method, confidence=confidence)


def _parse_linkedin_username(url: str) -> str | None:
    """Extract username from linkedin.com/in/<username> URL."""
    m = re.search(r"linkedin\.com/in/([A-Za-z0-9_\-]+)", url, re.IGNORECASE)
    return m.group(1) if m else None


def extract_from_linkedin(url: str) -> RawExtraction:
    """
    Fetch a LinkedIn profile via Proxycurl and return a RawExtraction.
    Falls back gracefully if no API key is set or the request fails.
    """
    ext = RawExtraction(source_name=SOURCE)

    api_key = os.environ.get("PROXYCURL_API_KEY")
    if not api_key:
        print(
            "[linkedin_extractor] PROXYCURL_API_KEY not set — skipping LinkedIn fetch. "
            "Set the key to enable live LinkedIn data extraction."
        )
        return ext

    # Normalise URL
    if not url.startswith("http"):
        url = f"https://{url}"

    try:
        import requests
        resp = requests.get(
            "https://nubela.co/proxycurl/api/v2/linkedin",
            params={"url": url},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 404:
            print(f"[linkedin_extractor] Profile not found: {url}")
            return ext
        if resp.status_code == 401:
            print("[linkedin_extractor] Invalid PROXYCURL_API_KEY")
            return ext
        resp.raise_for_status()
        data: dict = resp.json()
    except Exception as exc:
        print(f"[linkedin_extractor] Request failed: {exc}")
        return ext

    return _parse_proxycurl_response(data, url)


def _parse_proxycurl_response(data: dict, original_url: str) -> RawExtraction:
    ext = RawExtraction(source_name=SOURCE)

    # Name
    first = (data.get("first_name") or "").strip()
    last  = (data.get("last_name")  or "").strip()
    name  = f"{first} {last}".strip()
    if name:
        ext.full_name = _fv(name)

    # Email (Proxycurl returns personal_email / work_email with add-on)
    for key in ("personal_email", "work_email", "email"):
        email = data.get(key)
        if email and "@" in email:
            ext.emails.append(_fv(email.strip().lower()))

    # Headline
    headline = data.get("headline") or data.get("occupation")
    if headline:
        ext.headline = _fv(str(headline))

    # Location
    loc_parts = [
        data.get("city") or "",
        data.get("state") or "",
        data.get("country_full_name") or data.get("country") or "",
    ]
    loc_raw = ", ".join(p for p in loc_parts if p)
    if loc_raw:
        ext.location = _fv(parse_location(loc_raw), method="api_parsed")

    # Links — store the LinkedIn URL itself
    links: dict[str, Any] = {
        "linkedin": original_url,
        "github": None,
        "portfolio": None,
        "other": [],
    }
    ext.links = _fv(links)

    # Skills
    for skill_entry in data.get("skills", []) or []:
        name_s = skill_entry if isinstance(skill_entry, str) else (
            skill_entry.get("name", "") if isinstance(skill_entry, dict) else ""
        )
        if name_s:
            ext.skills.append(_fv(
                {"name": canonicalise_skill(name_s.strip()), "confidence": BASE_CONFIDENCE},
                method="api",
            ))

    # Experience (positions)
    for pos in data.get("experiences", []) or []:
        if not isinstance(pos, dict):
            continue
        company  = pos.get("company") or "Unknown"
        title    = pos.get("title")
        starts   = pos.get("starts_at") or {}
        ends     = pos.get("ends_at")   or {}
        start_str = f"{starts.get('year', '')}-{starts.get('month', 1):02d}" if starts.get("year") else None
        end_str   = f"{ends.get('year', '')}-{ends.get('month', 1):02d}"   if ends and ends.get("year") else "present"
        ext.experience.append(_fv({
            "company": str(company),
            "title":   str(title) if title else None,
            "start":   start_str,
            "end":     end_str,
            "summary": pos.get("description"),
        }, confidence=BASE_CONFIDENCE))

    # Education
    for edu in data.get("education", []) or []:
        if not isinstance(edu, dict):
            continue
        institution = edu.get("school") or "Unknown"
        degree      = edu.get("degree_name")
        field       = edu.get("field_of_study")
        ends        = edu.get("ends_at") or {}
        end_year    = ends.get("year") if ends else None
        ext.education.append(_fv({
            "institution": str(institution),
            "degree":      str(degree) if degree else None,
            "field":       str(field)  if field  else None,
            "end_year":    end_year,
        }, confidence=BASE_CONFIDENCE))

    return ext
