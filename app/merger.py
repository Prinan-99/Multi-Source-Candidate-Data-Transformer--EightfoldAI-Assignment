"""
Merger: combines multiple RawExtraction objects into a single CanonicalCandidate.

Conflict-resolution policy
──────────────────────────
• Scalar fields (name, headline, location, links, years_experience):
    Pick the FieldValue with the highest confidence.
    If two sources disagree AND their confidences are within 0.05 of each other,
    reduce overall_confidence by 0.05 (flagging the conflict without discarding either).

• Array fields (emails, phones):
    Union all values, normalise, deduplicate.

• Skills:
    Union across sources; if a skill appears in multiple sources its confidence
    is boosted: conf = 1 - product(1 - c_i for each source mentioning it).

• Experience / Education:
    Deduplicate by (company, title) key for experience and (institution, degree) for
    education. Most-confident entry wins on collision.

• Provenance:
    Every accepted value is recorded with its source and method.

• overall_confidence:
    Mean of field-level confidences, penalised by conflicts.
"""

from __future__ import annotations
import hashlib
import json
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")

from app.schema import (
    CanonicalCandidate,
    Education,
    Experience,
    FieldValue,
    Links,
    Location,
    ProvenanceEntry,
    RawExtraction,
    Skill,
)
from app.normalizers.phone import normalise_phones
from app.normalizers.date import years_between


def merge(extractions: list[RawExtraction], candidate_id: str | None = None) -> CanonicalCandidate:
    """Merge a list of per-source extractions into one canonical record."""
    if not extractions:
        return CanonicalCandidate(candidate_id=candidate_id or _generate_id("empty"))

    cid = candidate_id or _generate_id(
        "".join(
            (e.full_name.value if e.full_name else "")
            + "".join(v.value for v in e.emails)
            for e in extractions
        )
    )

    candidate = CanonicalCandidate(candidate_id=cid)
    provenance: list[ProvenanceEntry] = []
    field_confidences: list[float] = []
    conflicts = 0

    # ── name ──────────────────────────────────────────────────────────────
    name_values = [e.full_name for e in extractions if e.full_name]
    winner, had_conflict = _pick_scalar(name_values)
    if winner:
        candidate.full_name = winner.value
        provenance.append(_prov("full_name", winner))
        field_confidences.append(winner.confidence)
        if had_conflict:
            conflicts += 1

    # ── emails ────────────────────────────────────────────────────────────
    all_emails: list[str] = []
    for ext in extractions:
        for fv in ext.emails:
            addr = fv.value
            if isinstance(addr, str) and "@" in addr and addr not in all_emails:
                all_emails.append(addr)
                provenance.append(_prov("emails", fv))
    candidate.emails = all_emails
    if all_emails:
        field_confidences.append(0.90)

    # ── phones ────────────────────────────────────────────────────────────
    raw_phones = [fv.value for ext in extractions for fv in ext.phones if fv.value]
    normalised = normalise_phones([str(p) for p in raw_phones])
    candidate.phones = normalised
    for ext in extractions:
        for fv in ext.phones:
            if fv.value:
                provenance.append(_prov("phones", fv))
    if normalised:
        field_confidences.append(0.85)

    # ── location ──────────────────────────────────────────────────────────
    loc_values = [e.location for e in extractions if e.location]
    winner, had_conflict = _pick_scalar(loc_values)
    if winner:
        loc_dict = winner.value if isinstance(winner.value, dict) else {}
        candidate.location = Location(**{k: loc_dict.get(k) for k in ("city", "region", "country")})
        provenance.append(_prov("location", winner))
        field_confidences.append(winner.confidence)
        if had_conflict:
            conflicts += 1

    # ── links ─────────────────────────────────────────────────────────────
    merged_links: dict[str, Any] = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    for ext in extractions:
        if ext.links:
            d = ext.links.value if isinstance(ext.links.value, dict) else {}
            for key in ("linkedin", "github", "portfolio"):
                if d.get(key) and not merged_links[key]:
                    merged_links[key] = d[key]
            for o in (d.get("other") or []):
                if o not in merged_links["other"]:
                    merged_links["other"].append(o)
            provenance.append(_prov("links", ext.links))
    if any(merged_links.get(k) for k in ("linkedin", "github", "portfolio")):
        candidate.links = Links(**merged_links)
        field_confidences.append(0.90)

    # ── headline ──────────────────────────────────────────────────────────
    headline_values = [e.headline for e in extractions if e.headline]
    winner, _ = _pick_scalar(headline_values)
    if winner:
        candidate.headline = winner.value
        provenance.append(_prov("headline", winner))
        field_confidences.append(winner.confidence)

    # ── skills ────────────────────────────────────────────────────────────
    candidate.skills = _merge_skills(extractions, provenance)
    if candidate.skills:
        field_confidences.append(sum(s.confidence for s in candidate.skills) / len(candidate.skills))

    # ── experience ────────────────────────────────────────────────────────
    candidate.experience = _merge_experience(extractions, provenance)

    # ── education ─────────────────────────────────────────────────────────
    candidate.education = _merge_education(extractions, provenance)

    # ── years_experience (derived from experience entries) ────────────────
    total_years = _compute_years_experience(candidate.experience)
    if total_years is not None:
        candidate.years_experience = total_years
        field_confidences.append(0.70)
        provenance.append(ProvenanceEntry(
            field="years_experience",
            source="computed",
            method="summed_from_experience",
            confidence=0.70,
        ))

    # ── overall_confidence ────────────────────────────────────────────────
    if field_confidences:
        base = sum(field_confidences) / len(field_confidences)
        penalty = conflicts * 0.05
        candidate.overall_confidence = round(max(0.0, min(1.0, base - penalty)), 3)
    else:
        candidate.overall_confidence = 0.0

    candidate.provenance = provenance
    return candidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_scalar(values: list[FieldValue]) -> tuple[FieldValue | None, bool]:
    """
    Pick the highest-confidence value. Returns (winner, had_conflict).
    had_conflict is True when two sources give meaningfully different values
    AND have similar confidence (within 0.05).
    """
    if not values:
        return None, False
    sorted_vals = sorted(values, key=lambda v: v.confidence, reverse=True)
    winner = sorted_vals[0]
    if len(sorted_vals) < 2:
        return winner, False

    runner_up = sorted_vals[1]
    values_differ = str(winner.value).lower() != str(runner_up.value).lower()
    confidences_close = abs(winner.confidence - runner_up.confidence) <= 0.05
    had_conflict = values_differ and confidences_close
    return winner, had_conflict


def _merge_skills(
    extractions: list[RawExtraction],
    provenance: list[ProvenanceEntry],
) -> list[Skill]:
    """Union skills across sources; boost confidence when multiple sources agree."""
    # name → {source: confidence}
    skill_map: dict[str, dict[str, float]] = {}
    skill_fvs: dict[str, list[FieldValue]] = {}

    for ext in extractions:
        for fv in ext.skills:
            d = fv.value if isinstance(fv.value, dict) else {}
            name = d.get("name", "")
            if not name:
                continue
            skill_map.setdefault(name, {})[ext.source_name] = max(
                skill_map.get(name, {}).get(ext.source_name, 0),
                d.get("confidence", fv.confidence),
            )
            skill_fvs.setdefault(name, []).append(fv)

    result: list[Skill] = []
    for name, source_confs in skill_map.items():
        # Confidence boost: 1 - product(1 - c) across sources
        product = 1.0
        for c in source_confs.values():
            product *= (1.0 - c)
        combined = 1.0 - product
        combined = round(min(1.0, combined), 3)

        skill = Skill(name=name, confidence=combined, sources=list(source_confs.keys()))
        result.append(skill)
        for fv in skill_fvs[name]:
            provenance.append(_prov("skills", fv))

    # Sort by confidence descending
    result.sort(key=lambda s: -s.confidence)
    return result


def _dedup_entries(
    extractions: list[RawExtraction],
    provenance: list[ProvenanceEntry],
    field: str,
    key_fields: tuple[str, str],
    make_entry: Callable[[dict], _T],
) -> list[_T]:
    """
    Shared dedup loop for list fields (experience, education).
    Iterates ext.<field>, builds a two-part key from key_fields, keeps the
    highest-confidence entry per key, and records provenance.
    """
    seen: dict[str, _T] = {}
    seen_conf: dict[str, float] = {}
    for ext in extractions:
        for fv in getattr(ext, field):
            d = fv.value if isinstance(fv.value, dict) else {}
            k1 = (d.get(key_fields[0]) or "").strip()
            k2 = (d.get(key_fields[1]) or "").strip()
            key = f"{k1.lower()}|{k2.lower()}"
            if key not in seen or fv.confidence > seen_conf.get(key, 0):
                seen[key] = make_entry(d)
                seen_conf[key] = fv.confidence
                provenance.append(_prov(field, fv))
    return list(seen.values())


def _merge_experience(
    extractions: list[RawExtraction],
    provenance: list[ProvenanceEntry],
) -> list[Experience]:
    """Deduplicate by (company, title) key; highest confidence wins."""
    def make(d: dict) -> Experience:
        return Experience(
            company=(d.get("company") or "").strip() or "Unknown",
            title=(d.get("title") or "").strip() or None,
            start=d.get("start"),
            end=d.get("end"),
            summary=d.get("summary"),
        )
    entries = _dedup_entries(extractions, provenance, "experience", ("company", "title"), make)
    return sorted(entries, key=lambda e: e.start or "0000-00", reverse=True)


def _merge_education(
    extractions: list[RawExtraction],
    provenance: list[ProvenanceEntry],
) -> list[Education]:
    """Deduplicate by (institution, degree) key."""
    def make(d: dict) -> Education:
        return Education(
            institution=(d.get("institution") or "").strip() or "Unknown",
            degree=(d.get("degree") or "").strip() or None,
            field=d.get("field"),
            end_year=d.get("end_year"),
        )
    entries = _dedup_entries(extractions, provenance, "education", ("institution", "degree"), make)
    return sorted(entries, key=lambda e: -(e.end_year or 0))


def _compute_years_experience(experience: list[Experience]) -> float | None:
    """Sum up non-overlapping years of work experience."""
    total = 0.0
    any_valid = False
    for exp in experience:
        y = years_between(exp.start, exp.end)
        if y is not None:
            total += y
            any_valid = True
    return round(total, 1) if any_valid else None


def _prov(field: str, fv: FieldValue) -> ProvenanceEntry:
    return ProvenanceEntry(
        field=field,
        source=fv.source,
        method=fv.method,
        confidence=fv.confidence,
    )


def _generate_id(seed: str) -> str:
    return "cand_" + hashlib.sha256(seed.encode()).hexdigest()[:12]
