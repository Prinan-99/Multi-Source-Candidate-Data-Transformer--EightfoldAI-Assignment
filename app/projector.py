"""
Projector: applies an OutputConfig to a CanonicalCandidate and produces
the final dict that gets serialised to JSON.

This is the "required twist" — the same canonical record can be reshaped
at runtime without touching the pipeline.

Config capabilities
───────────────────
• fields       – select a subset and optionally rename / remap them
• from         – dotted path into the canonical record (supports [0] indexing)
• normalize    – "E164" | "canonical" | "ISO3166" (applied to the projected value)
• required     – if True and value is missing, behaviour is governed by on_missing
• on_missing   – "null" | "omit" | "error"
• include_confidence  – append overall_confidence to output
• include_provenance  – append provenance array to output
"""

from __future__ import annotations
import json
import re
from typing import Any

from app.schema import CanonicalCandidate, OutputConfig, FieldProjection
from app.normalizers.phone import to_e164
from app.normalizers.skills import canonicalise_skill


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def project(candidate: CanonicalCandidate, config: OutputConfig | None = None) -> dict[str, Any]:
    """
    Reshape a CanonicalCandidate into the final output dict.
    If config is None, emit the full canonical record unchanged.
    """
    if config is None:
        return _full_emit(candidate)

    raw = candidate.model_dump()
    output: dict[str, Any] = {}

    if config.fields:
        for fp in config.fields:
            source_path = fp.from_ or fp.path
            value = _resolve_path(raw, source_path)

            if value is None:
                if fp.required:
                    if config.on_missing == "error":
                        raise ValueError(f"Required field '{fp.path}' is missing")
                    elif config.on_missing == "omit":
                        continue
                    else:  # null
                        output[fp.path] = None
                elif config.on_missing == "omit":
                    continue
                else:
                    output[fp.path] = None
                continue

            value = _apply_normalise(value, fp.normalize)
            output[fp.path] = value
    else:
        output = _full_emit(candidate)

    if config.include_confidence:
        output["overall_confidence"] = candidate.overall_confidence

    if config.include_provenance:
        output["provenance"] = [p.model_dump() for p in candidate.provenance]

    return output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_emit(candidate: CanonicalCandidate) -> dict[str, Any]:
    """Emit the full canonical record as a plain dict (provenance + confidence included)."""
    d = candidate.model_dump()
    return d


def _resolve_path(data: Any, path: str) -> Any:
    """
    Traverse a dotted path with optional [N] index and [] spread syntax.

    Examples:
      "full_name"         → data["full_name"]
      "emails[0]"         → data["emails"][0]
      "skills[].name"     → [s["name"] for s in data["skills"]]
      "location.country"  → data["location"]["country"]
    """
    # Handle spread patterns before splitting on dots:
    # "skills[].name" → get data["skills"] then pluck "name" from each item
    spread_full = re.match(r"^(\w+)\[\]\.(.+)$", path)
    if spread_full:
        key, subpath = spread_full.group(1), spread_full.group(2)
        lst = data.get(key) if isinstance(data, dict) else None
        if isinstance(lst, list):
            results = [_resolve_path(item, subpath) for item in lst if item is not None]
            return results if results else None
        return None

    parts = path.split(".")
    current = data

    for part in parts:
        if current is None:
            return None

        # Indexed access: "emails[0]"
        idx_m = re.match(r"^(\w+)\[(\d+)\]$", part)
        if idx_m:
            key, idx = idx_m.group(1), int(idx_m.group(2))
            lst = current.get(key) if isinstance(current, dict) else None
            if isinstance(lst, list) and idx < len(lst):
                current = lst[idx]
            else:
                return None
            continue

        # Bare spread marker "skills[]" — return list as-is
        bare_spread = re.match(r"^(\w+)\[\]$", part)
        if bare_spread:
            key = bare_spread.group(1)
            current = current.get(key) if isinstance(current, dict) else None
            continue

        # Plain dict key or implicit list spread
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            current = [item.get(part) if isinstance(item, dict) else None for item in current]
        else:
            return None

    return current


def _apply_normalise(value: Any, normalize: str | None) -> Any:
    """Apply a normalisation directive to a projected value."""
    if not normalize:
        return value

    norm = normalize.upper()

    if norm == "E164":
        if isinstance(value, str):
            return to_e164(value) or value
        if isinstance(value, list):
            return [to_e164(str(v)) or v for v in value]

    elif norm == "CANONICAL":
        if isinstance(value, str):
            return canonicalise_skill(value)
        if isinstance(value, list):
            return [canonicalise_skill(str(v)) for v in value]

    elif norm == "ISO3166":
        # Already normalised by location extractor; just pass through
        return value

    return value
