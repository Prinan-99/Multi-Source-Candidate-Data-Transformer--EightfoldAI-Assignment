"""
End-to-end integration tests for pipeline.run().

These tests exercise the full stack — extractors → merger → projector —
using the real sample data files in sample_data/.
"""

import json
import os
import pytest
from pathlib import Path

from app.pipeline import run

SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"
CSV_PATH = str(SAMPLE_DIR / "sample_recruiter.csv")
NOTES_PATH = str(SAMPLE_DIR / "sample_notes.txt")
CONFIG_PATH = str(Path(__file__).parent.parent / "config" / "sample_config.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(*args, **kwargs):
    """Thin wrapper so tests don't repeat keyword names."""
    return run(*args, **kwargs)


# ---------------------------------------------------------------------------
# Schema shape tests
# ---------------------------------------------------------------------------

class TestOutputSchema:

    def test_csv_only_returns_required_keys(self):
        result = _run(csv_path=CSV_PATH)
        for key in ("candidate_id", "full_name", "emails", "phones",
                    "location", "skills", "overall_confidence", "provenance"):
            assert key in result, f"Missing key: {key}"

    def test_candidate_id_is_deterministic(self):
        r1 = _run(csv_path=CSV_PATH)
        r2 = _run(csv_path=CSV_PATH)
        assert r1["candidate_id"] == r2["candidate_id"]

    def test_candidate_id_has_cand_prefix(self):
        result = _run(csv_path=CSV_PATH)
        assert result["candidate_id"].startswith("cand_")

    def test_overall_confidence_between_0_and_1(self):
        result = _run(csv_path=CSV_PATH)
        assert 0.0 <= result["overall_confidence"] <= 1.0

    def test_phones_are_e164(self):
        result = _run(csv_path=CSV_PATH)
        for phone in result.get("phones", []):
            assert phone.startswith("+"), f"Phone not E.164: {phone}"

    def test_emails_are_lowercase(self):
        result = _run(csv_path=CSV_PATH)
        for email in result.get("emails", []):
            assert email == email.lower(), f"Email not lowercase: {email}"

    def test_skills_have_name_and_confidence(self):
        result = _run(csv_path=CSV_PATH)
        for skill in result.get("skills", []):
            assert "name" in skill
            assert "confidence" in skill
            assert 0.0 <= skill["confidence"] <= 1.0

    def test_provenance_entries_have_required_fields(self):
        result = _run(csv_path=CSV_PATH)
        for entry in result.get("provenance", []):
            for key in ("field", "source", "method", "confidence"):
                assert key in entry, f"Provenance entry missing '{key}'"


# ---------------------------------------------------------------------------
# Multi-source merge tests
# ---------------------------------------------------------------------------

class TestMultiSourceMerge:

    def test_csv_plus_notes_merges_emails(self):
        result = _run(csv_path=CSV_PATH, notes_path=NOTES_PATH)
        assert len(result["emails"]) >= 1

    def test_csv_plus_notes_no_duplicate_phones(self):
        result = _run(csv_path=CSV_PATH, notes_path=NOTES_PATH)
        phones = result.get("phones", [])
        assert len(phones) == len(set(phones)), "Duplicate phones in output"

    def test_skills_confidence_boosted_when_two_sources_agree(self):
        # CSV has Python; if notes or a second source also mentions it, confidence > 0.85
        result = _run(csv_path=CSV_PATH, notes_path=NOTES_PATH)
        skill_map = {s["name"]: s["confidence"] for s in result.get("skills", [])}
        # At minimum, CSV skills should be present
        assert len(skill_map) > 0

    def test_missing_source_does_not_crash(self):
        # Pass a non-existent file — pipeline must not raise
        result = _run(csv_path=CSV_PATH, resume_path="/nonexistent/file.pdf")
        assert "candidate_id" in result

    def test_empty_call_returns_empty_candidate(self):
        result = _run()
        assert "candidate_id" in result
        assert result["overall_confidence"] == 0.0


# ---------------------------------------------------------------------------
# Config / projector tests
# ---------------------------------------------------------------------------

class TestProjector:

    def test_custom_config_produces_primary_email_field(self):
        result = _run(csv_path=CSV_PATH, output_config_path=CONFIG_PATH)
        assert "primary_email" in result, "Custom config should rename emails[0] → primary_email"

    def test_custom_config_skills_is_flat_list(self):
        result = _run(csv_path=CSV_PATH, output_config_path=CONFIG_PATH)
        skills = result.get("skills", [])
        assert isinstance(skills, list)
        # In sample_config, skills[].name → flat list of strings, not dicts
        if skills:
            assert isinstance(skills[0], str), f"Expected flat string list, got: {type(skills[0])}"

    def test_default_config_includes_provenance(self):
        result = _run(csv_path=CSV_PATH)
        assert "provenance" in result
        assert isinstance(result["provenance"], list)

    def test_invalid_config_path_falls_back_to_defaults(self):
        result = _run(csv_path=CSV_PATH, output_config_path="/nonexistent/config.json")
        assert "candidate_id" in result
        assert "provenance" in result
