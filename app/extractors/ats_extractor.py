"""
Structured source extractor: ATS JSON blob.

ATS systems (Greenhouse, Lever, Workday, etc.) export candidate data as JSON
but with field names that do NOT match our canonical schema. This extractor
maps the most common ATS field name variants to our internal fields.

Field name variants handled:
  name:     first_name+last_name, fullName, candidate_name, applicant_name
  email:    email_address, emailAddresses[], work_email, personal_email
  phone:    phone_numbers[], mobile_phone, work_phone, phoneNumber
  location: current_location, address, city+country, location_name
  headline: current_title, job_title, headline, position
  company:  current_employer, current_company, employer_name
  skills:   skill_tags[], skills[], competencies[]
  experience: work_history[], positions[], employment_history[]
  education:  education_history[], schools[], degrees[]

Confidence: 0.80 (semi-structured; field names vary across ATS vendors)
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from app.schema import FieldValue, RawExtraction
from app.normalizers.phone import to_e164
from app.normalizers.location import parse_location
from app.normalizers.skills import canonicalise_skill
from app.normalizers.date import to_year_month

SOURCE = "ats_json"
BASE_CONFIDENCE = 0.80


def _fv(value: Any, method: str = "direct", confidence: float = BASE_CONFIDENCE) -> FieldValue:
    return FieldValue(value=value, source=SOURCE, method=method, confidence=confidence)


def _get(d: dict, *keys: str) -> Any:
    """Try multiple key names, return first non-empty match."""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "" and v != []:
            return v
    return None


def extract_from_ats(path: str | Path) -> list[RawExtraction]:
    """
    Parse an ATS JSON blob. Handles both a single candidate object
    and a list of candidate objects. Never raises.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[ats_extractor] Cannot read {path}: {exc}")
        return []

    # Normalise to list
    if isinstance(raw, dict):
        # Might be wrapped: {"candidates": [...]} or {"data": {...}}
        if "candidates" in raw:
            records = raw["candidates"] if isinstance(raw["candidates"], list) else [raw["candidates"]]
        elif "data" in raw:
            records = raw["data"] if isinstance(raw["data"], list) else [raw["data"]]
        else:
            records = [raw]
    elif isinstance(raw, list):
        records = raw
    else:
        print(f"[ats_extractor] Unexpected JSON shape in {path}")
        return []

    return [_parse_record(r) for r in records if isinstance(r, dict)]


def _parse_record(r: dict) -> RawExtraction:
    ext = RawExtraction(source_name=SOURCE)

    # ── Name ──────────────────────────────────────────────────────────────
    name = _get(r, "full_name", "fullName", "name", "candidate_name", "applicant_name")
    if not name:
        first = _get(r, "first_name", "firstName") or ""
        last  = _get(r, "last_name",  "lastName")  or ""
        name  = f"{first} {last}".strip() or None
    if name:
        ext.full_name = _fv(str(name))

    # ── Emails ────────────────────────────────────────────────────────────
    email_val = _get(r, "email", "email_address", "emailAddress",
                     "work_email", "personal_email", "primary_email")
    if isinstance(email_val, str) and "@" in email_val:
        ext.emails.append(_fv(email_val.strip().lower()))
    email_list = _get(r, "emails", "email_addresses", "emailAddresses")
    if isinstance(email_list, list):
        for e in email_list:
            addr = e if isinstance(e, str) else e.get("value", "") if isinstance(e, dict) else ""
            if "@" in addr and addr not in [x.value for x in ext.emails]:
                ext.emails.append(_fv(addr.strip().lower()))

    # ── Phones ────────────────────────────────────────────────────────────
    phone_val = _get(r, "phone", "phone_number", "phoneNumber",
                     "mobile_phone", "work_phone", "mobile")
    if phone_val:
        normalised = to_e164(str(phone_val))
        ext.phones.append(_fv(normalised or str(phone_val),
                               confidence=BASE_CONFIDENCE if normalised else 0.5))
    phone_list = _get(r, "phones", "phone_numbers", "phoneNumbers")
    if isinstance(phone_list, list):
        for p in phone_list:
            raw_p = p if isinstance(p, str) else p.get("value", "") if isinstance(p, dict) else ""
            if raw_p:
                normalised = to_e164(str(raw_p))
                ext.phones.append(_fv(normalised or str(raw_p),
                                       confidence=BASE_CONFIDENCE if normalised else 0.5))

    # ── Location ──────────────────────────────────────────────────────────
    loc_raw = _get(r, "location", "current_location", "location_name", "address")
    if not loc_raw:
        city    = _get(r, "city") or ""
        country = _get(r, "country") or ""
        loc_raw = f"{city}, {country}".strip(", ") or None
    if loc_raw:
        ext.location = _fv(parse_location(str(loc_raw)), method="parsed")

    # ── Links ─────────────────────────────────────────────────────────────
    links: dict[str, Any] = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    li = _get(r, "linkedin", "linkedin_url", "linkedinUrl", "linkedin_profile")
    if li:
        links["linkedin"] = str(li)
    gh = _get(r, "github", "github_url", "githubUrl", "github_profile")
    if gh:
        links["github"] = str(gh)
    portfolio = _get(r, "portfolio", "website", "personal_website", "portfolio_url")
    if portfolio:
        links["portfolio"] = str(portfolio)
    if any(links[k] for k in ("linkedin", "github", "portfolio")):
        ext.links = _fv(links)

    # ── Headline ──────────────────────────────────────────────────────────
    title   = _get(r, "headline", "current_title", "job_title", "title",
                   "current_position", "position")
    company = _get(r, "current_company", "current_employer", "employer",
                   "employer_name", "company")
    if title and company:
        ext.headline = _fv(f"{title} at {company}")
    elif title:
        ext.headline = _fv(str(title))
    elif company:
        ext.headline = _fv(str(company), confidence=0.6)

    # ── Skills ────────────────────────────────────────────────────────────
    skill_raw = _get(r, "skills", "skill_tags", "competencies",
                     "technologies", "tech_stack", "tags")
    if isinstance(skill_raw, list):
        for s in skill_raw:
            name_s = s if isinstance(s, str) else s.get("name", "") if isinstance(s, dict) else ""
            name_s = name_s.strip()
            if name_s:
                ext.skills.append(_fv(
                    {"name": canonicalise_skill(name_s), "confidence": BASE_CONFIDENCE},
                    method="direct",
                ))
    elif isinstance(skill_raw, str):
        import re
        for s in re.split(r"[,;|]+", skill_raw):
            s = s.strip()
            if s:
                ext.skills.append(_fv(
                    {"name": canonicalise_skill(s), "confidence": BASE_CONFIDENCE},
                    method="direct",
                ))

    # ── Experience ────────────────────────────────────────────────────────
    exp_list = _get(r, "work_history", "positions", "employment_history",
                    "experience", "work_experience", "jobs")
    if isinstance(exp_list, list):
        for job in exp_list:
            if not isinstance(job, dict):
                continue
            exp_company = _get(job, "company", "employer", "organization", "company_name") or "Unknown"
            exp_title   = _get(job, "title", "job_title", "position", "role")
            exp_start   = to_year_month(str(_get(job, "start_date", "startDate", "from") or ""))
            exp_end     = to_year_month(str(_get(job, "end_date", "endDate", "to", "until") or "")) or "present"
            exp_summary = _get(job, "summary", "description", "responsibilities")
            ext.experience.append(_fv({
                "company": str(exp_company),
                "title":   str(exp_title) if exp_title else None,
                "start":   exp_start,
                "end":     exp_end,
                "summary": str(exp_summary) if exp_summary else None,
            }, confidence=0.80))
    elif company or title:
        ext.experience.append(_fv({
            "company": str(company or "Unknown"),
            "title":   str(title) if title else None,
            "start":   None, "end": None, "summary": None,
        }, confidence=0.75))

    # ── Education ─────────────────────────────────────────────────────────
    edu_list = _get(r, "education", "education_history", "schools",
                    "degrees", "academic_history")
    if isinstance(edu_list, list):
        for edu in edu_list:
            if not isinstance(edu, dict):
                continue
            institution = _get(edu, "school", "institution", "university",
                                "college", "school_name") or "Unknown"
            degree      = _get(edu, "degree", "degree_type", "qualification")
            field       = _get(edu, "field", "major", "field_of_study", "subject")
            end_year_raw = _get(edu, "end_year", "graduation_year", "year",
                                "end_date", "graduationDate")
            end_year = None
            if end_year_raw:
                import re
                m = re.search(r"\b(19|20)\d{2}\b", str(end_year_raw))
                end_year = int(m.group(0)) if m else None
            ext.education.append(_fv({
                "institution": str(institution),
                "degree":      str(degree) if degree else None,
                "field":       str(field) if field else None,
                "end_year":    end_year,
            }, confidence=0.80))

    return ext
