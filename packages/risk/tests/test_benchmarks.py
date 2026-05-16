"""Unit tests for industry-benchmark lookup and comparison."""
from __future__ import annotations

import pytest

from packages.risk.benchmarks import (
    COMPARABLE_RATIOS,
    IndustryBenchmark,
    benchmark_for,
    compare,
    load_benchmarks,
)
from packages.shared.models import FinancialRatios


def test_load_benchmarks_contains_required_codes():
    benchmarks = load_benchmarks()
    required = {
        "01", "10", "13", "20", "21", "24", "25", "26", "27", "28",
        "29", "41", "45", "46", "47", "49", "55", "56", "62", "64",
    }
    missing = required - set(benchmarks.keys())
    assert not missing, f"missing required NACE codes: {missing}"


def test_load_benchmarks_skips_meta():
    benchmarks = load_benchmarks()
    assert "_meta" not in benchmarks
    for key in benchmarks:
        assert not key.startswith("_")


def test_load_benchmarks_returns_industry_benchmark_models():
    benchmarks = load_benchmarks()
    for code, entry in benchmarks.items():
        assert isinstance(entry, IndustryBenchmark)
        assert entry.nace_code == code
        assert entry.name
        assert entry.source
        assert entry.median_ratios


def test_every_benchmark_entry_has_source_year_metadata():
    benchmarks = load_benchmarks()
    for entry in benchmarks.values():
        assert "BACH" in entry.source
        assert "2023" in entry.source


def test_benchmark_for_two_digit_code_returns_entry():
    b = benchmark_for("62")
    assert b is not None
    assert b.nace_code == "62"
    assert "Computer programming" in b.name


def test_benchmark_for_four_digit_code_reduces_to_two_digit():
    b = benchmark_for("62.01")
    assert b is not None and b.nace_code == "62"
    assert benchmark_for("6201").nace_code == "62"
    assert benchmark_for("6202").nace_code == "62"


def test_benchmark_for_none_returns_none():
    assert benchmark_for(None) is None


def test_benchmark_for_unknown_code_returns_none():
    # 99 is "Activities of extraterritorial organisations" — intentionally
    # not in our table.
    assert benchmark_for("99") is None


def test_benchmark_for_empty_and_garbage_inputs():
    assert benchmark_for("") is None
    assert benchmark_for("abc") is None  # no digits
    assert benchmark_for("1") is None    # only one digit


def test_compare_classifies_above_p75():
    b = benchmark_for("62")
    assert b is not None
    band = b.band("current_ratio")
    assert band is not None
    ratios = FinancialRatios(year=2023, current_ratio=band.p75 + 0.5)
    result = compare(ratios, b)
    assert result["current_ratio"] == "above_p75"


def test_compare_classifies_below_p25():
    b = benchmark_for("62")
    band = b.band("debt_to_equity")
    ratios = FinancialRatios(year=2023, debt_to_equity=band.p25 - 0.1)
    result = compare(ratios, b)
    assert result["debt_to_equity"] == "below_p25"


def test_compare_classifies_median_band():
    b = benchmark_for("62")
    band = b.band("roe")
    ratios = FinancialRatios(year=2023, roe=band.median)
    result = compare(ratios, b)
    assert result["roe"] == "median_band"


def test_compare_classifies_boundary_as_median_band():
    """p25 and p75 are the boundary — values equal to them are inside the band."""
    b = benchmark_for("62")
    band = b.band("current_ratio")
    inside_low = FinancialRatios(year=2023, current_ratio=band.p25)
    inside_high = FinancialRatios(year=2023, current_ratio=band.p75)
    assert compare(inside_low, b)["current_ratio"] == "median_band"
    assert compare(inside_high, b)["current_ratio"] == "median_band"


def test_compare_returns_unknown_for_missing_value():
    b = benchmark_for("62")
    ratios = FinancialRatios(year=2023)  # everything None
    result = compare(ratios, b)
    for name in COMPARABLE_RATIOS:
        assert result[name] == "unknown"


def test_compare_keys_cover_all_comparable_ratios():
    b = benchmark_for("62")
    ratios = FinancialRatios(year=2023, current_ratio=1.45)
    result = compare(ratios, b)
    assert set(result.keys()) == set(COMPARABLE_RATIOS)


def test_comparable_ratios_match_financial_ratios_attributes():
    """Defends against renaming a ratio on FinancialRatios without updating us."""
    valid = set(FinancialRatios.model_fields.keys())
    for name in COMPARABLE_RATIOS:
        assert name in valid, f"{name} not in FinancialRatios.model_fields"


def test_band_returns_none_for_missing_ratio():
    b = IndustryBenchmark(
        nace_code="99", name="x", source="test", median_ratios={}
    )
    assert b.band("current_ratio") is None
