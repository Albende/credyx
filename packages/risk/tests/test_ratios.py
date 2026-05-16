"""Unit tests for deterministic ratio calculation."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from packages.risk.ratios import (
    compute_ratios,
    compute_ratios_for_filing,
    compute_ratios_series,
    extract_financial_lines,
)
from packages.shared.models import FilingType, FinancialFiling


def _make_legacy(year: int, **lines: Any) -> FinancialFiling:
    """Flat-key payload — the shape early adapters and tests use."""
    return FinancialFiling(
        company_id="X",
        year=year,
        type=FilingType.ANNUAL_REPORT,
        period_end=date(year, 12, 31),
        currency="EUR",
        structured_data=lines,
    )


def _make_unified(
    year: int,
    *,
    balance_sheet: dict[str, Any] | None = None,
    income_statement: dict[str, Any] | None = None,
    cash_flow: dict[str, Any] | None = None,
    currency: str = "EUR",
) -> FinancialFiling:
    """Unified schema — what XBRL/ESEF/EDGAR parsers produce."""
    data: dict[str, Any] = {
        "currency": currency,
        "period_end": f"{year}-12-31",
        "consolidated": True,
        "balance_sheet": balance_sheet or {},
        "income_statement": income_statement or {},
        "cash_flow": cash_flow or {},
        "raw_concepts": {},
    }
    return FinancialFiling(
        company_id="X",
        year=year,
        type=FilingType.ANNUAL_REPORT,
        period_end=date(year, 12, 31),
        currency=currency,
        structured_data=data,
    )


# ---------------------------------------------------------------------------
# Legacy flat-key compatibility (preserves the original test surface)
# ---------------------------------------------------------------------------


def test_ratios_basic_current_and_de():
    f = _make_legacy(
        2023,
        current_assets=200,
        current_liabilities=100,
        total_liabilities=300,
        equity=150,
        net_income=30,
        total_assets=450,
        revenue=1000,
        cost_of_sales=600,
    )
    r = compute_ratios([f])[0]
    assert r.current_ratio == 2.0
    assert r.debt_to_equity == 2.0
    assert r.roe == 0.2
    assert r.roa == 30 / 450
    assert r.gross_margin == 0.4


def test_ratios_yoy_growth_when_prior_year_present():
    a = _make_legacy(2023, revenue=1100, total_assets=500, equity=200)
    b = _make_legacy(2022, revenue=1000, total_assets=480, equity=180)
    rs = {r.year: r for r in compute_ratios([a, b])}
    assert rs[2023].revenue_growth_yoy == pytest.approx(0.1)


def test_ratios_partial_lines_yield_none_for_uncomputable():
    f = _make_legacy(2023, revenue=1000)
    r = compute_ratios([f])
    assert r and r[0].current_ratio is None
    assert r[0].altman_z_score is None
    assert r[0].roe is None


def test_extract_lines_handles_aliases_and_strings():
    f = _make_legacy(2023, Turnover="1,234.50", TotalAssets="2000")
    lines = extract_financial_lines(f)
    assert lines and lines.revenue == 1234.5
    assert lines.total_assets == 2000


# ---------------------------------------------------------------------------
# Unified schema (the canonical shape produced by XBRL / ESEF / EDGAR parsers)
# ---------------------------------------------------------------------------


def test_unified_schema_full_ratios_correct():
    f = _make_unified(
        2024,
        balance_sheet={
            "total_assets": 1000.0,
            "current_assets": 400.0,
            "non_current_assets": 600.0,
            "cash_and_equivalents": 100.0,
            "inventories": 150.0,
            "trade_receivables": 80.0,
            "total_liabilities": 600.0,
            "current_liabilities": 200.0,
            "non_current_liabilities": 400.0,
            "total_equity": 400.0,
            "share_capital": 100.0,
            "retained_earnings": 250.0,
        },
        income_statement={
            "revenue": 2000.0,
            "gross_profit": 800.0,
            "operating_profit": 300.0,
            "ebitda": 350.0,
            "net_income": 200.0,
            "depreciation_amortization": 50.0,
            "interest_expense": 20.0,
        },
        cash_flow={
            "operating_cf": 250.0,
            "investing_cf": -100.0,
            "financing_cf": -50.0,
            "free_cash_flow": 150.0,
        },
    )
    r = compute_ratios_for_filing(f)
    assert r is not None
    assert r.current_ratio == pytest.approx(2.0)
    assert r.quick_ratio == pytest.approx((400 - 150) / 200)
    assert r.debt_to_equity == pytest.approx(1.5)
    assert r.debt_to_assets == pytest.approx(0.6)
    assert r.roe == pytest.approx(0.5)
    assert r.roa == pytest.approx(0.2)
    assert r.gross_margin == pytest.approx(0.4)
    assert r.net_margin == pytest.approx(0.1)
    assert r.working_capital == pytest.approx(200.0)
    assert r.altman_z_score is not None
    # YoY growth requires a prior year — single-filing call returns None.
    assert r.revenue_growth_yoy is None


def test_unified_schema_compute_ratios_single_filing_polymorphic():
    f = _make_unified(
        2024,
        balance_sheet={"total_assets": 100.0, "total_liabilities": 40.0, "total_equity": 60.0},
        income_statement={"revenue": 200.0, "net_income": 20.0},
    )
    r = compute_ratios(f)
    assert r is not None
    assert r.year == 2024
    assert r.debt_to_assets == pytest.approx(0.4)
    assert r.net_margin == pytest.approx(0.1)


def test_unified_schema_missing_field_yields_none():
    f = _make_unified(
        2024,
        balance_sheet={"total_assets": 500.0},  # nothing else
        income_statement={"revenue": 1000.0},
    )
    r = compute_ratios_for_filing(f)
    assert r is not None
    assert r.current_ratio is None
    assert r.quick_ratio is None
    assert r.debt_to_equity is None
    assert r.roe is None
    assert r.working_capital is None
    assert r.altman_z_score is None


def test_unified_schema_zero_denominator_yields_none():
    f = _make_unified(
        2024,
        balance_sheet={
            "total_assets": 1000.0, "current_assets": 100.0,
            "current_liabilities": 0.0, "total_equity": 0.0,
            "total_liabilities": 500.0, "retained_earnings": 100.0,
        },
        income_statement={"revenue": 0.0, "net_income": 50.0, "operating_profit": 10.0},
    )
    r = compute_ratios_for_filing(f)
    assert r is not None
    assert r.current_ratio is None
    assert r.roe is None  # equity = 0
    assert r.gross_margin is None  # revenue = 0 (and gross_profit missing)


def test_no_structured_data_returns_none():
    f = FinancialFiling(
        company_id="X",
        year=2024,
        type=FilingType.ANNUAL_REPORT,
        period_end=date(2024, 12, 31),
        currency="EUR",
        structured_data=None,
        document_url="https://example.com/filing.pdf",
        document_format="pdf",
    )
    assert compute_ratios_for_filing(f) is None
    assert compute_ratios([f]) == []
    assert compute_ratios_series([f]) == []


# ---------------------------------------------------------------------------
# Multi-year series + YoY growth
# ---------------------------------------------------------------------------


def test_series_sorts_descending_and_fills_yoy_growth():
    y22 = _make_unified(
        2022,
        balance_sheet={"total_assets": 800.0, "total_equity": 300.0, "total_liabilities": 500.0},
        income_statement={"revenue": 1000.0, "net_income": 80.0},
    )
    y23 = _make_unified(
        2023,
        balance_sheet={"total_assets": 900.0, "total_equity": 350.0, "total_liabilities": 550.0},
        income_statement={"revenue": 1100.0, "net_income": 95.0},
    )
    y24 = _make_unified(
        2024,
        balance_sheet={"total_assets": 1000.0, "total_equity": 400.0, "total_liabilities": 600.0},
        income_statement={"revenue": 1320.0, "net_income": 120.0},
    )
    series = compute_ratios_series([y22, y24, y23])
    assert [r.year for r in series] == [2024, 2023, 2022]
    assert series[0].revenue_growth_yoy == pytest.approx(0.2)
    assert series[1].revenue_growth_yoy == pytest.approx(0.1)
    # No prior year for 2022 — must be None, not 0.
    assert series[2].revenue_growth_yoy is None


def test_series_yoy_skipped_when_intermediate_year_missing():
    y22 = _make_unified(2022, income_statement={"revenue": 1000.0})
    y24 = _make_unified(2024, income_statement={"revenue": 1500.0})
    series = compute_ratios_series([y22, y24])
    by_year = {r.year: r for r in series}
    # 2024 has no immediately-prior 2023 → YoY undefined.
    assert by_year[2024].revenue_growth_yoy is None


# ---------------------------------------------------------------------------
# Altman Z-score thresholds (safe high vs. distressed)
# ---------------------------------------------------------------------------


def test_altman_z_safe_zone_above_three():
    """Healthy public manufacturer profile: Z > 3.0 = 'safe'."""
    f = _make_unified(
        2024,
        balance_sheet={
            "total_assets": 1000.0,
            "current_assets": 600.0,
            "current_liabilities": 100.0,
            "total_liabilities": 200.0,
            "total_equity": 800.0,
            "retained_earnings": 600.0,
        },
        income_statement={
            "revenue": 2000.0,
            "operating_profit": 400.0,
            "net_income": 300.0,
        },
    )
    r = compute_ratios_for_filing(f)
    assert r is not None and r.altman_z_score is not None
    assert r.altman_z_score > 3.0, f"expected safe (>3), got {r.altman_z_score}"


def test_altman_z_distress_zone_below_one_point_eight():
    """Distressed profile: low retained earnings, high leverage, negative WC."""
    f = _make_unified(
        2024,
        balance_sheet={
            "total_assets": 1000.0,
            "current_assets": 100.0,
            "current_liabilities": 400.0,
            "total_liabilities": 900.0,
            "total_equity": 100.0,
            "retained_earnings": -200.0,
        },
        income_statement={
            "revenue": 300.0,
            "operating_profit": -50.0,
            "net_income": -80.0,
        },
    )
    r = compute_ratios_for_filing(f)
    assert r is not None and r.altman_z_score is not None
    assert r.altman_z_score < 1.8, f"expected distressed (<1.8), got {r.altman_z_score}"


def test_altman_z_none_when_required_input_missing():
    f = _make_unified(
        2024,
        balance_sheet={
            "total_assets": 1000.0,
            "current_assets": 400.0,
            "current_liabilities": 200.0,
            "total_liabilities": 500.0,
            "total_equity": 500.0,
            # retained_earnings missing
        },
        income_statement={"revenue": 1000.0, "operating_profit": 100.0},
    )
    r = compute_ratios_for_filing(f)
    assert r is not None
    assert r.altman_z_score is None
