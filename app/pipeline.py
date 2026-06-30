"""
Pipeline orchestrator.

Flow: detect → extract → merge → project → validate → return

Each stage degrades gracefully: a failing extractor logs a warning and is
skipped; the pipeline continues with whatever it has.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any

from app.schema import OutputConfig, RawExtraction, FieldProjection
from app.merger import merge
from app.projector import project


def run(
    csv_path: str | None = None,
    github_url: str | None = None,
    resume_path: str | None = None,
    ats_json_path: str | None = None,
    notes_path: str | None = None,
    linkedin_url: str | None = None,
    output_config_path: str | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    """
    Run the full pipeline and return the final output dict.

    At least one structured source (csv_path or ats_json_path) AND one
    unstructured source (github_url or resume_path) should be provided,
    but the pipeline works with any non-zero subset.
    """
    extractions: list[RawExtraction] = []
    warnings: list[str] = []

    # ── Structured sources ────────────────────────────────────────────────
    if csv_path:
        try:
            from app.extractors.csv_extractor import extract_from_csv
            rows = extract_from_csv(csv_path)
            if rows:
                extractions.append(rows[0])
                if len(rows) > 1:
                    warnings.append(
                        f"CSV has {len(rows)} rows — only row 1 was processed. "
                        "Use batch mode for multiple candidates."
                    )
            print(f"[pipeline] CSV: using row 1 of {len(rows)} from {csv_path}")
        except Exception as exc:
            print(f"[pipeline] CSV extractor failed: {exc}", file=sys.stderr)

    if notes_path:
        try:
            from app.extractors.notes_extractor import extract_from_notes
            note = extract_from_notes(notes_path)
            extractions.append(note)
            print(f"[pipeline] Notes: extracted from {notes_path}")
        except Exception as exc:
            print(f"[pipeline] Notes extractor failed: {exc}", file=sys.stderr)

    if ats_json_path:
        try:
            from app.extractors.ats_extractor import extract_from_ats
            rows = extract_from_ats(ats_json_path)
            extractions.extend(rows)
            print(f"[pipeline] ATS JSON: extracted {len(rows)} record(s)")
        except Exception as exc:
            print(f"[pipeline] ATS extractor failed: {exc}", file=sys.stderr)

    # ── Unstructured sources ──────────────────────────────────────────────
    if linkedin_url:
        try:
            from app.extractors.linkedin_extractor import extract_from_linkedin
            li = extract_from_linkedin(linkedin_url)
            extractions.append(li)
            print(f"[pipeline] LinkedIn: extracted profile for {linkedin_url}")
        except Exception as exc:
            print(f"[pipeline] LinkedIn extractor failed: {exc}", file=sys.stderr)

    if github_url:
        try:
            from app.extractors.github_extractor import extract_from_github
            gh = extract_from_github(github_url)
            extractions.append(gh)
            print(f"[pipeline] GitHub: extracted profile for {github_url}")
        except Exception as exc:
            print(f"[pipeline] GitHub extractor failed: {exc}", file=sys.stderr)

    if resume_path:
        try:
            from app.extractors.resume_extractor import extract_from_resume
            res = extract_from_resume(resume_path)
            extractions.append(res)
            print(f"[pipeline] Resume PDF: extracted from {resume_path}")
        except Exception as exc:
            print(f"[pipeline] Resume extractor failed: {exc}", file=sys.stderr)

    if not extractions:
        print("[pipeline] WARNING: no sources produced any data.", file=sys.stderr)

    # ── Merge ─────────────────────────────────────────────────────────────
    canonical = merge(extractions, candidate_id=candidate_id)

    # ── Load output config ────────────────────────────────────────────────
    config: OutputConfig | None = None
    if output_config_path:
        try:
            raw_cfg = json.loads(Path(output_config_path).read_text())
            config = OutputConfig.model_validate(raw_cfg)
        except Exception as exc:
            print(f"[pipeline] Invalid output config, using defaults: {exc}", file=sys.stderr)

    # ── Project ───────────────────────────────────────────────────────────
    output = project(canonical, config)

    if warnings:
        output["_warnings"] = warnings

    return output
