"""Unit tests for deterministic ratio calculation."""
from __future__ import annotations

from datetime import date

from packages.risk.ratios import compute_ratios, extract_financial_lines
from packages.shared.models import FilingType, FinancialFiling


def _make(year: int, **lines) -> FinancialFiling:
    return FinancialFiling(
        company_id="X",
        year=year,
        type=FilingType.ANNUAL_REPORT,
        period_end=date(year, 12, 31),
        currency="EUR",
        structured_data=lines,
    )


def test_ratios_basic_current_and_de():
    f = _make(
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
    a = _make(2023, revenue=1100, total_assets=500, equity=200)
    b = _make(2022, revenue=1000, total_assets=480, equity=180)
    rs = {r.year: r for r in compute_ratios([a, b])}
    assert rs[2023].revenue_growth_yoy == pytest.approx(0.1)


def test_ratios_partial_lines_yield_none_for_uncomputable():
    # We have revenue but nothing else — ratios that need balance-sheet data
    # must come back as None, not 0 or a guess.
    f = _make(2023, revenue=1000)
    r = compute_ratios([f])
    assert r and r[0].current_ratio is None
    assert r[0].altman_z_score is None
    assert r[0].roe is None


def test_extract_lines_handles_aliases_and_strings():
    f = _make(2023, Turnover="1,234.50", TotalAssets="2000")
    lines = extract_financial_lines(f)
    assert lines and lines.revenue == 1234.5
    assert lines.total_assets == 2000


import pytest  # noqa: E402  (kept at bottom so file is self-contained)
