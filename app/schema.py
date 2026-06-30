"""
Canonical schema for the candidate data transformer.

Two layers:
  1. CanonicalCandidate — the internal, fully-normalised record produced by the merger.
     This is the source of truth; every extractor and normaliser targets it.
  2. OutputConfig — runtime config that reshapes a CanonicalCandidate into the final
     JSON delivered to the caller (field selection, renaming, per-field normalisation,
     missing-value policy).
"""

from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class ProvenanceEntry(BaseModel):
    field: str
    source: str          # e.g. "recruiter_csv", "github_api", "resume_pdf"
    method: str          # e.g. "regex", "direct", "inferred"
    confidence: float    # 0.0–1.0


class Skill(BaseModel):
    name: str                    # canonical skill name
    confidence: float            # 0.0–1.0
    sources: list[str] = []      # which sources mentioned this skill


class Experience(BaseModel):
    company: str
    title: Optional[str] = None
    start: Optional[str] = None  # YYYY-MM
    end: Optional[str] = None    # YYYY-MM or "present"
    summary: Optional[str] = None


class Education(BaseModel):
    institution: str
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


class Location(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None   # ISO 3166-1 alpha-2


class Links(BaseModel):
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list[str] = []


# ---------------------------------------------------------------------------
# Internal canonical record (produced by merger, consumed by projector)
# ---------------------------------------------------------------------------

class CanonicalCandidate(BaseModel):
    candidate_id: str
    full_name: Optional[str] = None
    emails: list[str] = []
    phones: list[str] = []             # E.164
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list[Skill] = []
    experience: list[Experience] = []
    education: list[Education] = []
    provenance: list[ProvenanceEntry] = []
    overall_confidence: float = 0.0


# ---------------------------------------------------------------------------
# Per-source raw extraction result (merger input)
# ---------------------------------------------------------------------------

class FieldValue(BaseModel):
    """A single extracted value with its source metadata."""
    value: Any
    source: str
    method: str
    confidence: float


class RawExtraction(BaseModel):
    """What a single extractor returns. All fields are optional FieldValues."""
    source_name: str
    full_name: Optional[FieldValue] = None
    emails: list[FieldValue] = []
    phones: list[FieldValue] = []
    location: Optional[FieldValue] = None   # value is a dict matching Location
    links: Optional[FieldValue] = None      # value is a dict matching Links
    headline: Optional[FieldValue] = None
    years_experience: Optional[FieldValue] = None
    skills: list[FieldValue] = []           # each value is {"name": ..., "confidence": ...}
    experience: list[FieldValue] = []       # each value is a dict matching Experience
    education: list[FieldValue] = []        # each value is a dict matching Education


# ---------------------------------------------------------------------------
# Output config (the "required twist" — reshapes canonical → final JSON)
# ---------------------------------------------------------------------------

class FieldProjection(BaseModel):
    path: str                                           # output key name
    from_: Optional[str] = Field(None, alias="from")   # source path in canonical record
    type: str = "string"
    required: bool = False
    normalize: Optional[str] = None                    # "E164", "canonical", "ISO3166", etc.

    model_config = {"populate_by_name": True}


class OutputConfig(BaseModel):
    fields: Optional[list[FieldProjection]] = None   # None → emit all canonical fields
    include_confidence: bool = True
    include_provenance: bool = True
    on_missing: Literal["null", "omit", "error"] = "null"
