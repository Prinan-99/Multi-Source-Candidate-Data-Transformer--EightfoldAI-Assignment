"""
Unstructured source extractor: Resume PDF.

Uses pdfplumber for text extraction, then regex heuristics to identify:
  - Name (first non-blank line, often largest text)
  - Email addresses
  - Phone numbers
  - LinkedIn / GitHub URLs
  - Skills section
  - Experience section (company / title / dates)
  - Education section

Design principle: prefer returning None over inventing a value.
Confidence is lower than structured sources because we're parsing prose.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from app.schema import FieldValue, RawExtraction
from app.normalizers.phone import parse_phone
from app.normalizers.date import to_year_month
from app.normalizers.location import parse_location
from app.normalizers.skills import canonicalise_skill

SOURCE = "resume_pdf"
BASE_CONFIDENCE = 0.75


def _fv(value: Any, method: str = "regex", confidence: float = BASE_CONFIDENCE) -> FieldValue:
    return FieldValue(value=value, source=SOURCE, method=method, confidence=confidence)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?<!\d)(\+?[\d][\d\s\-().]{6,14}\d)(?!\d)"
)
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9_\-]+)", re.IGNORECASE)
_GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9_\-]+)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s,)>]+", re.IGNORECASE)

# Section header detection
_SECTION_RE = re.compile(
    r"^(experience|work experience|employment|professional experience"
    r"|education|academic|skills|technical skills|key skills"
    r"|projects|certifications|summary|objective|profile)",
    re.IGNORECASE,
)

# Date range: "Jan 2020 – Dec 2022"  or "2019 - present"
_DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4})"
    r"\s*[\-—to]+\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4}|[Pp]resent|[Cc]urrent)",
    re.IGNORECASE,
)

_SKILL_SECTION_NAMES = {"skills", "technical skills", "key skills", "core competencies",
                         "technologies", "tools", "tech stack"}
_EXP_SECTION_NAMES = {"experience", "work experience", "employment",
                       "professional experience", "career"}
_EDU_SECTION_NAMES = {"education", "academic", "academic background"}


def extract_from_resume(path: str | Path) -> RawExtraction:
    """Parse a PDF resume and return a RawExtraction. Never raises."""
    ext = RawExtraction(source_name=SOURCE)
    path = Path(path)

    try:
        import pdfplumber
    except ImportError:
        print("[resume_extractor] pdfplumber not installed; skipping PDF extraction")
        return ext

    try:
        with pdfplumber.open(str(path)) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:
        print(f"[resume_extractor] Cannot open PDF {path}: {exc}")
        return ext

    full_text = "\n".join(pages_text)
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

    if not lines:
        return ext

    _extract_contact(ext, full_text, lines)
    _extract_skills(ext, full_text, lines)
    _extract_experience(ext, lines)
    _extract_education(ext, lines)

    return ext


def _extract_contact(ext: RawExtraction, text: str, lines: list[str]) -> None:
    # Name: first non-empty line that isn't an email/phone/URL and is short
    for line in lines[:8]:
        if (
            not _EMAIL_RE.search(line)
            and not _PHONE_RE.search(line)
            and not _URL_RE.search(line)
            and len(line.split()) <= 6
            and len(line) >= 3
        ):
            ext.full_name = _fv(line, method="first_line", confidence=0.70)
            break

    # Emails
    for addr in _EMAIL_RE.findall(text):
        ext.emails.append(_fv(addr.lower()))

    # Phones
    seen_phones: set[str] = set()
    for raw_phone in _PHONE_RE.findall(text):
        target, conf = parse_phone(raw_phone, BASE_CONFIDENCE)
        if target not in seen_phones:
            seen_phones.add(target)
            ext.phones.append(_fv(target, confidence=conf))

    # LinkedIn
    m = _LINKEDIN_RE.search(text)
    links: dict[str, Any] = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    if m:
        links["linkedin"] = f"https://linkedin.com/in/{m.group(1)}"
    # GitHub
    m2 = _GITHUB_RE.search(text)
    if m2:
        links["github"] = f"https://github.com/{m2.group(1)}"
    if links["linkedin"] or links["github"]:
        ext.links = _fv(links, method="regex_url")

    # Location: look for "City, Country" near the top 10 lines
    for line in lines[:10]:
        if re.search(r",\s*[A-Za-z]{2,}", line) and not _EMAIL_RE.search(line):
            loc = parse_location(line)
            if loc.get("country") or loc.get("city"):
                ext.location = _fv(loc, method="regex_location", confidence=0.65)
                break


# Known non-skill tokens (section headers, generic labels, city/context words)
_NON_SKILLS = {
    "languages", "language", "tools", "technologies", "frameworks",
    "soft skills", "hard skills", "data", "architecture", "models",
    "agriculture", "agronomist", "leadership", "teamwork",
    "outcomes", "decisions", "visualization", "tirupur", "coimbatore",
    "bangalore", "chennai", "mumbai", "delhi",  # city names
    "references", "certifications", "certification", "portfolio",
    "profile", "summary", "objective",
    "knowledge bases", "hallucination", "config", "github-config",
    "on aws", "for nlp", "farming", "backed",
}

_NOISE_RE = re.compile(
    r"(https?://|www\."                               # URLs
    r"|\.(?:tech|com|io|ai|org|net|in|dev)(?:\s|$)"  # domain extensions
    r"|\d+%"                                          # percentages
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
    r"|\b(19|20)\d{2}\b"                              # 4-digit years
    r")",
    re.IGNORECASE,
)

# Sentence-like connector words (only flag when 2+ word token)
_SENTENCE_RE = re.compile(
    r"\b(to|the|for|using|with|based|on|in|of|by|an|assistant|reduced|driven|bases)\b",
    re.IGNORECASE,
)


def _is_valid_skill_token(token: str) -> bool:
    """Return True only for tokens that look like actual skill names."""
    t = token.strip().rstrip(".,")
    if not t:
        return False
    # Too short or too long
    if len(t) < 2 or len(t) > 30:
        return False
    # Too many words — sentence fragment or project name
    words = t.split()
    if len(words) > 3:
        return False
    # Starts or ends with parenthesis
    if t.startswith("(") or t.endswith(")"):
        return False
    # Known non-skill labels (check full token and each hyphen-split word)
    t_lower = t.lower()
    if t_lower in _NON_SKILLS:
        return False
    if any(w in _NON_SKILLS for w in re.split(r"[-\s]+", t_lower)):
        return False
    # URL / domain / date / percentage noise
    if _NOISE_RE.search(t):
        return False
    # Sentence-connector words in multi-word tokens
    if len(words) > 1 and _SENTENCE_RE.search(t):
        return False
    return True


_SECTION_HEADER_PREFIX_RE = re.compile(
    r"^(programming languages?|languages?|frameworks?|libraries|tools?"
    r"|development tools?|ml\s*:|machine learning|web technologies"
    r"|databases?|cloud|devops|other)\s*[:–\-]\s*",
    re.IGNORECASE,
)


def _extract_skills(ext: RawExtraction, text: str, lines: list[str]) -> None:
    """Find skills section and extract comma/pipe/bullet separated items."""
    in_skills = False
    collected: list[str] = []

    for line in lines:
        header_m = _SECTION_RE.match(line)
        if header_m:
            section = header_m.group(1).lower()
            in_skills = section in _SKILL_SECTION_NAMES
            continue
        if in_skills:
            # Stop at next major section
            if _SECTION_RE.match(line) and line.lower().split()[0] not in _SKILL_SECTION_NAMES:
                break
            # Strip inline sub-headers like "Programming Languages: Python, Java"
            clean_line = _SECTION_HEADER_PREFIX_RE.sub("", line).strip()
            for token in re.split(r"[,|•·▪\t]+", clean_line):
                token = token.strip(" ·•–-")
                if _is_valid_skill_token(token):
                    collected.append(token)

    for s in collected:
        canonical = canonicalise_skill(s)
        if canonical:
            ext.skills.append(_fv(
                {"name": canonical, "confidence": BASE_CONFIDENCE},
                method="section_parse",
            ))


def _extract_experience(ext: RawExtraction, lines: list[str]) -> None:
    """Heuristic experience section parser."""
    in_exp = False
    current: dict[str, Any] | None = None

    for line in lines:
        header_m = _SECTION_RE.match(line)
        if header_m:
            section = header_m.group(1).lower()
            if section in _EXP_SECTION_NAMES:
                in_exp = True
                if current:
                    ext.experience.append(_fv(current, method="section_parse", confidence=0.70))
                    current = None
                continue
            else:
                if in_exp and current:
                    ext.experience.append(_fv(current, method="section_parse", confidence=0.70))
                    current = None
                in_exp = False
                continue

        if not in_exp:
            continue

        date_m = _DATE_RANGE_RE.search(line)
        if date_m:
            # Start of a new experience entry
            if current:
                ext.experience.append(_fv(current, method="section_parse", confidence=0.70))
            current = {
                "company": None,
                "title": None,
                "start": to_year_month(date_m.group(1)),
                "end": to_year_month(date_m.group(2)),
                "summary": None,
            }
            # Title / company often on the same line or adjacent
            remainder = _DATE_RANGE_RE.sub("", line).strip(" |–-·")
            if remainder:
                parts = re.split(r"\s*[|–@·]\s*", remainder)
                if len(parts) >= 2:
                    current["title"] = parts[0].strip()
                    current["company"] = parts[1].strip()
                else:
                    current["company"] = remainder
        elif current is not None:
            # Continuation: accumulate summary
            if current["summary"]:
                current["summary"] += " " + line
            else:
                # First continuation line after date → often company/title
                if not current["company"]:
                    current["company"] = line
                elif not current["title"] and len(line.split()) <= 8:
                    current["title"] = line
                else:
                    current["summary"] = line

    if current:
        ext.experience.append(_fv(current, method="section_parse", confidence=0.70))


def _extract_education(ext: RawExtraction, lines: list[str]) -> None:
    """Heuristic education section parser."""
    in_edu = False
    current: dict[str, Any] | None = None

    _DEGREE_WORDS = re.compile(
        r"\b(B\.?Tech|M\.?Tech|B\.?E|M\.?E|B\.?Sc|M\.?Sc|PhD|Bachelor|Master|MBA|B\.?A|M\.?A"
        r"|B\.?Com|M\.?Com|Diploma|Associate|Doctor)\b",
        re.IGNORECASE,
    )

    for line in lines:
        header_m = _SECTION_RE.match(line)
        if header_m:
            section = header_m.group(1).lower()
            if section in _EDU_SECTION_NAMES:
                in_edu = True
                if current:
                    ext.education.append(_fv(current, method="section_parse", confidence=0.70))
                    current = None
                continue
            else:
                if in_edu and current:
                    ext.education.append(_fv(current, method="section_parse", confidence=0.70))
                    current = None
                in_edu = False
                continue

        if not in_edu:
            continue

        year_m = re.search(r"\b(20[012]\d|199\d)\b", line)
        degree_m = _DEGREE_WORDS.search(line)

        if degree_m or year_m:
            if current:
                ext.education.append(_fv(current, method="section_parse", confidence=0.70))
            current = {
                "institution": None,
                "degree": degree_m.group(0) if degree_m else None,
                "field": None,
                "end_year": int(year_m.group(0)) if year_m else None,
            }
            remainder = line
            if degree_m:
                remainder = _DEGREE_WORDS.sub("", remainder)
            if year_m:
                remainder = re.sub(r"\b(20[012]\d|199\d)\b", "", remainder)
            # Strip trailing status words like "PURSUING", "COMPLETED", "PRESENT"
            remainder = re.sub(r"\b(pursuing|completed|present|ongoing|expected)\b", "", remainder, flags=re.IGNORECASE)
            # Strip leading/trailing punctuation, dots, dashes, pipes
            remainder = remainder.strip(" ,–-|.·")
            # Remove double spaces
            remainder = re.sub(r"\s{2,}", " ", remainder).strip()
            if remainder:
                current["institution"] = remainder
        elif current and not current["institution"]:
            clean = line.strip(" ,–-|.·")
            clean = re.sub(r"\b(pursuing|completed|present|ongoing|expected)\b", "", clean, flags=re.IGNORECASE).strip()
            current["institution"] = clean if clean else None

    if current:
        ext.education.append(_fv(current, method="section_parse", confidence=0.70))
