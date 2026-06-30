"""Tests for normalisation modules."""

import pytest
from app.normalizers.phone import to_e164, normalise_phones
from app.normalizers.date import to_year_month, years_between
from app.normalizers.location import parse_location
from app.normalizers.skills import canonicalise_skill, canonicalise_skill_list


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------

class TestPhone:
    def test_e164_passthrough(self):
        assert to_e164("+14155552671") == "+14155552671"

    def test_us_number_no_country_code(self):
        assert to_e164("415-555-2671", "US") == "+14155552671"

    def test_indian_number(self):
        assert to_e164("+919876543210") == "+919876543210"

    def test_us_formatted(self):
        assert to_e164("(415) 867-5309", "US") == "+14158675309"

    def test_invalid_returns_none(self):
        assert to_e164("not-a-phone") is None

    def test_empty_returns_none(self):
        assert to_e164("") is None

    def test_none_returns_none(self):
        assert to_e164(None) is None  # type: ignore[arg-type]

    def test_deduplication(self):
        # Default region is IN — same Indian number in different formats deduplicates
        phones = normalise_phones(["+919876543210", "9876543210", "+14155552671"])
        assert len(phones) == 2
        assert "+919876543210" in phones
        assert "+14155552671" in phones

    def test_garbage_source_does_not_crash(self):
        # Edge case: garbage source mixed with valid numbers
        result = normalise_phones(["garbage", "+14155552671", "123"])
        assert "+14155552671" in result


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

class TestDate:
    def test_year_month_iso(self):
        assert to_year_month("2021-03") == "2021-03"

    def test_month_name_year(self):
        assert to_year_month("Jan 2020") == "2020-01"

    def test_month_abbr_year(self):
        assert to_year_month("Mar 2019") == "2019-03"

    def test_year_only(self):
        assert to_year_month("2020") == "2020-01"

    def test_present_keyword(self):
        assert to_year_month("present") == "present"
        assert to_year_month("Current") == "present"

    def test_none_input(self):
        assert to_year_month(None) is None

    def test_garbage_returns_none(self):
        assert to_year_month("not a date at all!!!") is None

    def test_years_between(self):
        years = years_between("2020-01", "2022-01")
        assert abs(years - 2.0) < 0.1

    def test_years_between_present(self):
        years = years_between("2020-01", "present")
        assert years is not None and years > 4  # it's 2026

    def test_years_between_none_start(self):
        assert years_between(None, "2022-01") is None


# ---------------------------------------------------------------------------
# Location normalisation
# ---------------------------------------------------------------------------

class TestLocation:
    def test_city_comma_country(self):
        loc = parse_location("San Francisco, US")
        assert loc["city"] == "San Francisco"
        assert loc["country"] == "US"

    def test_city_space_country(self):
        loc = parse_location("Chennai India")
        assert loc["city"] == "Chennai"
        assert loc["country"] == "IN"

    def test_known_city_lookup(self):
        loc = parse_location("Bangalore")
        assert loc["city"] == "Bangalore"
        assert loc["country"] == "IN"
        assert loc["region"] == "KA"

    def test_country_only(self):
        loc = parse_location("India")
        assert loc["country"] == "IN"

    def test_none_input(self):
        loc = parse_location(None)
        assert loc == {"city": None, "region": None, "country": None}

    def test_unknown_city_preserved(self):
        loc = parse_location("Smalltown")
        # Unknown city — preserved in city field, not invented
        assert loc["city"] == "Smalltown"
        assert loc["country"] is None


# ---------------------------------------------------------------------------
# Skills canonicalisation
# ---------------------------------------------------------------------------

class TestSkills:
    def test_python_alias(self):
        assert canonicalise_skill("python") == "Python"
        assert canonicalise_skill("Python3") == "Python"
        assert canonicalise_skill("py") == "Python"

    def test_ml_alias(self):
        assert canonicalise_skill("ml") == "Machine Learning"

    def test_postgres_alias(self):
        assert canonicalise_skill("postgres") == "PostgreSQL"

    def test_unknown_title_cased(self):
        result = canonicalise_skill("some obscure tool")
        assert result == "Some Obscure Tool"

    def test_deduplication(self):
        result = canonicalise_skill_list(["Python", "python", "py", "JavaScript", "js"])
        assert result.count("Python") == 1
        assert result.count("JavaScript") == 1
        assert len(result) == 2

    def test_empty_list(self):
        assert canonicalise_skill_list([]) == []
