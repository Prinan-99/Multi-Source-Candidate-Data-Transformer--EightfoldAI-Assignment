"""Tests for the merger and edge cases."""

import pytest
from app.schema import FieldValue, RawExtraction
from app.merger import merge, _pick_scalar


def _fv(value, source="test", method="direct", confidence=0.85):
    return FieldValue(value=value, source=source, method=method, confidence=confidence)


# ---------------------------------------------------------------------------
# Scalar merge: conflict resolution
# ---------------------------------------------------------------------------

class TestPickScalar:
    def test_single_value(self):
        fv = _fv("Alice")
        winner, conflict = _pick_scalar([fv])
        assert winner.value == "Alice"
        assert conflict is False

    def test_higher_confidence_wins(self):
        low = _fv("Alice", confidence=0.6)
        high = _fv("Alice B.", confidence=0.9)
        winner, _ = _pick_scalar([low, high])
        assert winner.value == "Alice B."

    def test_conflict_detected_when_values_differ_and_confidence_similar(self):
        a = _fv("Alice", confidence=0.85)
        b = _fv("Bob", confidence=0.85)
        winner, conflict = _pick_scalar([a, b])
        assert conflict is True

    def test_no_conflict_when_confidence_gap_large(self):
        a = _fv("Alice", confidence=0.90)
        b = _fv("Bob", confidence=0.70)
        _, conflict = _pick_scalar([a, b])
        assert conflict is False

    def test_empty_list(self):
        winner, conflict = _pick_scalar([])
        assert winner is None
        assert conflict is False


# ---------------------------------------------------------------------------
# Merge: multi-source integration
# ---------------------------------------------------------------------------

class TestMerge:
    def _make_extraction(self, source, name=None, email=None, phone=None, skills=None):
        ext = RawExtraction(source_name=source)
        if name:
            ext.full_name = _fv(name, source=source)
        if email:
            ext.emails = [_fv(email, source=source)]
        if phone:
            ext.phones = [_fv(phone, source=source)]
        if skills:
            for s in skills:
                ext.skills.append(_fv({"name": s, "confidence": 0.8}, source=source))
        return ext

    def test_empty_extractions_returns_valid_candidate(self):
        result = merge([])
        assert result.candidate_id.startswith("cand_")
        assert result.full_name is None
        assert result.emails == []
        assert result.overall_confidence == 0.0

    def test_single_source(self):
        ext = self._make_extraction("csv", name="Jane Doe", email="jane@example.com")
        result = merge([ext])
        assert result.full_name == "Jane Doe"
        assert "jane@example.com" in result.emails

    def test_higher_confidence_name_wins(self):
        csv_ext = self._make_extraction("recruiter_csv", name="Jane D.")
        csv_ext.full_name = _fv("Jane D.", source="recruiter_csv", confidence=0.85)
        gh_ext = self._make_extraction("github_api", name="Jane Doe")
        gh_ext.full_name = _fv("Jane Doe", source="github_api", confidence=0.90)
        result = merge([csv_ext, gh_ext])
        assert result.full_name == "Jane Doe"

    def test_emails_are_unioned(self):
        a = self._make_extraction("csv", email="work@corp.com")
        b = self._make_extraction("github", email="personal@gmail.com")
        result = merge([a, b])
        assert "work@corp.com" in result.emails
        assert "personal@gmail.com" in result.emails

    def test_skills_confidence_boosted_across_sources(self):
        a = self._make_extraction("csv", skills=["Python"])
        b = self._make_extraction("github", skills=["Python"])
        result = merge([a, b])
        python_skill = next((s for s in result.skills if s.name == "Python"), None)
        assert python_skill is not None
        # Confidence should be boosted above 0.8 (single source value)
        assert python_skill.confidence > 0.8
        assert len(python_skill.sources) == 2

    def test_provenance_recorded(self):
        ext = self._make_extraction("csv", name="Test User")
        result = merge([ext])
        name_prov = [p for p in result.provenance if p.field == "full_name"]
        assert len(name_prov) == 1
        assert name_prov[0].source == "csv"

    def test_garbage_source_doesnt_crash(self):
        # Edge case: empty extraction (simulates a failed extractor)
        empty = RawExtraction(source_name="broken_source")
        normal = self._make_extraction("csv", name="Alice", email="alice@test.com")
        result = merge([empty, normal])
        assert result.full_name == "Alice"

    def test_duplicate_emails_deduplicated(self):
        a = self._make_extraction("csv", email="shared@example.com")
        b = self._make_extraction("github", email="shared@example.com")
        result = merge([a, b])
        assert result.emails.count("shared@example.com") == 1

    def test_conflict_reduces_confidence(self):
        a = RawExtraction(source_name="source_a")
        a.full_name = _fv("Alice Smith", source="source_a", confidence=0.85)
        b = RawExtraction(source_name="source_b")
        b.full_name = _fv("Alicia Smith", source="source_b", confidence=0.85)
        result_conflict = merge([a, b])

        c = RawExtraction(source_name="source_c")
        c.full_name = _fv("Bob Jones", source="source_c", confidence=0.85)
        result_no_conflict = merge([c])

        # Conflict case should have lower or equal confidence
        assert result_conflict.overall_confidence <= result_no_conflict.overall_confidence


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_null_source(self):
        """All sources return empty extractions — should not crash."""
        extractions = [RawExtraction(source_name=f"source_{i}") for i in range(3)]
        result = merge(extractions)
        assert result.candidate_id is not None
        assert result.full_name is None

    def test_phone_normalisation_in_merge(self):
        """Phones in different formats should be deduplicated after normalisation."""
        ext1 = RawExtraction(source_name="csv")
        ext1.phones = [_fv("+14155552671", source="csv")]
        ext2 = RawExtraction(source_name="resume")
        ext2.phones = [_fv("415-555-2671", source="resume")]  # same number
        result = merge([ext1, ext2])
        assert result.phones.count("+14155552671") == 1

    def test_candidate_id_deterministic(self):
        """Same inputs → same candidate_id."""
        ext = RawExtraction(source_name="csv")
        ext.full_name = _fv("Jane Doe")
        ext.emails = [_fv("jane@example.com")]
        r1 = merge([ext])
        r2 = merge([ext])
        assert r1.candidate_id == r2.candidate_id
