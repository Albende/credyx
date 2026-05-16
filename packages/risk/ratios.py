"""Deterministic financial ratio extraction.

Adapters write a unified ``structured_data`` schema (see
``packages/risk/xbrl_esef.py`` and the US/JP/KR adapters for canonical
producers):

    {
      "currency": "EUR" | "USD" | ...,
      "period_end": "YYYY-MM-DD",
      "consolidated": bool,
      "balance_sheet": {
          "total_assets", "current_assets", "non_current_assets",
          "cash_and_equivalents", "inventories", "trade_receivables",
          "total_liabilities", "current_liabilities", "non_current_liabilities",
          "total_equity", "share_capital", "retained_earnings",
      },
      "income_statement": {
          "revenue", "gross_profit", "operating_profit", "ebitda",
          "net_income", "depreciation_amortization", "interest_expense",
      },
      "cash_flow": {
          "operating_cf", "investing_cf", "financing_cf", "free_cash_flow",
      },
      "raw_concepts": {...},
    }

This module computes deterministic ratios from that schema. Older
flat-key payloads (used by some early adapters and the existing tests)
are still understood via the alias fallback path. Anything we cannot
extract becomes ``None`` — never zero, never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, overload

from packages.shared.models import FinancialFiling, FinancialRatios


@dataclass
class FinancialLines:
    """Normalized line items extracted from a single year of filings."""

    year: int
    revenue: float | None = None
    cost_of_sales: float | None = None
    gross_profit: float | None = None
    operating_profit: float | None = None
    net_income: float | None = None
    ebit: float | None = None
    ebitda: float | None = None
    depreciation_amortization: float | None = None
    interest_expense: float | None = None
    current_assets: float | None = None
    non_current_assets: float | None = None
    cash: float | None = None
    inventory: float | None = None
    receivables: float | None = None
    total_assets: float | None = None
    current_liabilities: float | None = None
    non_current_liabilities: float | None = None
    total_liabilities: float | None = None
    long_term_debt: float | None = None
    equity: float | None = None
    share_capital: float | None = None
    retained_earnings: float | None = None
    operating_cf: float | None = None
    investing_cf: float | None = None
    financing_cf: float | None = None
    free_cash_flow: float | None = None


# Mapping from FinancialLines fields to the unified schema section + key.
_UNIFIED_MAP: dict[str, tuple[str, str]] = {
    # Balance sheet
    "total_assets": ("balance_sheet", "total_assets"),
    "current_assets": ("balance_sheet", "current_assets"),
    "non_current_assets": ("balance_sheet", "non_current_assets"),
    "cash": ("balance_sheet", "cash_and_equivalents"),
    "inventory": ("balance_sheet", "inventories"),
    "receivables": ("balance_sheet", "trade_receivables"),
    "total_liabilities": ("balance_sheet", "total_liabilities"),
    "current_liabilities": ("balance_sheet", "current_liabilities"),
    "non_current_liabilities": ("balance_sheet", "non_current_liabilities"),
    "equity": ("balance_sheet", "total_equity"),
    "share_capital": ("balance_sheet", "share_capital"),
    "retained_earnings": ("balance_sheet", "retained_earnings"),
    # Income statement
    "revenue": ("income_statement", "revenue"),
    "gross_profit": ("income_statement", "gross_profit"),
    "operating_profit": ("income_statement", "operating_profit"),
    "ebitda": ("income_statement", "ebitda"),
    "net_income": ("income_statement", "net_income"),
    "depreciation_amortization": ("income_statement", "depreciation_amortization"),
    "interest_expense": ("income_statement", "interest_expense"),
    # Cash flow
    "operating_cf": ("cash_flow", "operating_cf"),
    "investing_cf": ("cash_flow", "investing_cf"),
    "financing_cf": ("cash_flow", "financing_cf"),
    "free_cash_flow": ("cash_flow", "free_cash_flow"),
}


# Legacy flat-key aliases used by adapters that have not yet migrated to
# the unified schema (and by the early unit tests).
_LINE_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "revenue", "turnover", "salesrevenue", "totalrevenue", "netsales",
        "totalnetsales", "operatingrevenue", "totaloperatingrevenue",
    ],
    "cost_of_sales": ["costofsales", "costofrevenue", "costofgoodssold", "cogs"],
    "gross_profit": ["grossprofit"],
    "operating_profit": ["operatingprofit", "operatingincome", "ebit"],
    "net_income": ["netincome", "profitfortheyear", "netprofit", "profitloss"],
    "ebitda": ["ebitda"],
    "depreciation_amortization": [
        "depreciationamortization", "depreciationandamortisation",
        "depreciationandamortization",
    ],
    "interest_expense": ["interestexpense", "financecosts"],
    "current_assets": ["currentassets", "totalcurrentassets"],
    "non_current_assets": ["noncurrentassets", "totalnoncurrentassets"],
    "cash": ["cash", "cashandcashequivalents"],
    "inventory": ["inventory", "inventories"],
    "receivables": ["receivables", "tradereceivables", "accountsreceivable"],
    "total_assets": ["totalassets", "assets"],
    "current_liabilities": ["currentliabilities", "totalcurrentliabilities"],
    "non_current_liabilities": ["noncurrentliabilities", "totalnoncurrentliabilities"],
    "total_liabilities": ["totalliabilities", "liabilities"],
    "long_term_debt": ["longtermdebt", "noncurrentdebt", "longtermborrowings"],
    "equity": ["totalequity", "equity", "stockholdersequity", "shareholdersequity"],
    "share_capital": ["sharecapital", "issuedcapital"],
    "retained_earnings": ["retainedearnings"],
    "operating_cf": ["operatingcashflow", "cashfromoperations", "operatingcf"],
    "investing_cf": ["investingcashflow", "cashfrominvesting", "investingcf"],
    "financing_cf": ["financingcashflow", "cashfromfinancing", "financingcf"],
    "free_cash_flow": ["freecashflow", "fcf"],
}


_UNIFIED_SECTIONS = {"balance_sheet", "income_statement", "cash_flow"}


def _normalize_key(k: str) -> str:
    return "".join(ch for ch in k.lower() if ch.isalnum())


def _coerce_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):  # bool is an int subclass — exclude.
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.replace(",", "").replace(" ", "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _is_unified(data: dict[str, Any]) -> bool:
    return any(isinstance(data.get(s), dict) for s in _UNIFIED_SECTIONS)


def _extract_unified(data: dict[str, Any], year: int) -> FinancialLines:
    out = FinancialLines(year=year)
    for field, (section, key) in _UNIFIED_MAP.items():
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        val = _coerce_number(block.get(key))
        if val is not None:
            setattr(out, field, val)
    return out


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _extract_legacy(data: dict[str, Any], year: int) -> FinancialLines:
    flat = _flatten(data)
    norm: dict[str, float | None] = {}
    for k, v in flat.items():
        leaf = _normalize_key(k.split(".")[-1])
        coerced = _coerce_number(v)
        # Preserve the first non-None value seen for a normalized leaf.
        if leaf not in norm or norm[leaf] is None:
            norm[leaf] = coerced

    out = FinancialLines(year=year)
    for field, aliases in _LINE_ALIASES.items():
        for alias in aliases:
            if alias in norm and norm[alias] is not None:
                setattr(out, field, norm[alias])
                break
    return out


def extract_financial_lines(filing: FinancialFiling) -> FinancialLines | None:
    """Pull a FinancialLines record from a filing's structured_data, if any.

    Prefers the unified schema (``balance_sheet`` / ``income_statement`` /
    ``cash_flow`` sub-dicts) and falls back to the legacy flat-key aliases
    for older adapters and tests. Always derives gross_profit and EBIT
    from available inputs where possible.
    """
    if not filing.structured_data:
        return None
    data = filing.structured_data

    if _is_unified(data):
        out = _extract_unified(data, filing.year)
        # If sections exist but didn't carry a key, also try legacy aliases
        # on a flat view of the same dict so we don't lose adapter-specific
        # extra fields like cost_of_sales or long_term_debt.
        legacy = _extract_legacy(data, filing.year)
        for f in fields(out):
            if getattr(out, f.name) is None:
                v = getattr(legacy, f.name)
                if v is not None:
                    setattr(out, f.name, v)
    else:
        out = _extract_legacy(data, filing.year)

    # Derived values: never overwrite explicit ones.
    if out.gross_profit is None and out.revenue is not None and out.cost_of_sales is not None:
        out.gross_profit = out.revenue - out.cost_of_sales
    if out.ebit is None and out.operating_profit is not None:
        out.ebit = out.operating_profit
    if (
        out.ebitda is None
        and out.ebit is not None
        and out.depreciation_amortization is not None
    ):
        out.ebitda = out.ebit + out.depreciation_amortization
    if (
        out.free_cash_flow is None
        and out.operating_cf is not None
        and out.investing_cf is not None
    ):
        out.free_cash_flow = out.operating_cf + out.investing_cf
    return out


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _ratios_from_lines(
    lines: FinancialLines,
    prev: FinancialLines | None,
) -> FinancialRatios:
    l = lines
    working_capital = (
        l.current_assets - l.current_liabilities
        if l.current_assets is not None and l.current_liabilities is not None
        else None
    )
    quick_numerator = (
        l.current_assets - (l.inventory or 0)
        if l.current_assets is not None
        else None
    )
    revenue_growth = None
    if (
        prev is not None
        and l.revenue is not None
        and prev.revenue is not None
        and prev.revenue != 0
    ):
        revenue_growth = (l.revenue - prev.revenue) / prev.revenue

    return FinancialRatios(
        year=l.year,
        current_ratio=_safe_div(l.current_assets, l.current_liabilities),
        quick_ratio=_safe_div(quick_numerator, l.current_liabilities),
        debt_to_equity=_safe_div(l.total_liabilities, l.equity),
        debt_to_assets=_safe_div(l.total_liabilities, l.total_assets),
        roe=_safe_div(l.net_income, l.equity),
        roa=_safe_div(l.net_income, l.total_assets),
        gross_margin=_safe_div(l.gross_profit, l.revenue),
        net_margin=_safe_div(l.net_income, l.revenue),
        working_capital=working_capital,
        altman_z_score=_altman_z(l),
        revenue_growth_yoy=revenue_growth,
    )


def compute_ratios_for_filing(filing: FinancialFiling) -> FinancialRatios | None:
    """Compute ratios for a single filing, with no prior-year context.

    ``revenue_growth_yoy`` will be ``None`` because it requires the
    previous year. Use ``compute_ratios_series`` to populate YoY growth.
    """
    lines = extract_financial_lines(filing)
    if lines is None:
        return None
    return _ratios_from_lines(lines, prev=None)


def compute_ratios_series(filings: list[FinancialFiling]) -> list[FinancialRatios]:
    """Compute ratios for each filing year, sorted by year desc.

    Filings sharing a year are merged (first non-None wins). YoY growth
    is computed against the immediately-prior reporting year if present.
    """
    by_year: dict[int, FinancialLines] = {}
    for f in filings:
        lines = extract_financial_lines(f)
        if lines is None:
            continue
        existing = by_year.get(f.year)
        if existing is None:
            by_year[f.year] = lines
        else:
            for fld in fields(lines):
                if getattr(existing, fld.name) is None:
                    setattr(existing, fld.name, getattr(lines, fld.name))

    results: list[FinancialRatios] = []
    for year in sorted(by_year.keys(), reverse=True):
        results.append(_ratios_from_lines(by_year[year], by_year.get(year - 1)))
    return results


@overload
def compute_ratios(arg: FinancialFiling) -> FinancialRatios | None: ...
@overload
def compute_ratios(arg: list[FinancialFiling]) -> list[FinancialRatios]: ...


def compute_ratios(
    arg: FinancialFiling | list[FinancialFiling],
) -> FinancialRatios | list[FinancialRatios] | None:
    """Compute deterministic financial ratios.

    Polymorphic: pass a single ``FinancialFiling`` to get a single
    ``FinancialRatios | None`` back, or a list to get a per-year series
    (equivalent to ``compute_ratios_series``).
    """
    if isinstance(arg, FinancialFiling):
        return compute_ratios_for_filing(arg)
    return compute_ratios_series(arg)


def _altman_z(l: FinancialLines) -> float | None:
    """Altman Z-score for public manufacturers (classic 1968 form).

    Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
    where:
      A = working capital / total assets
      B = retained earnings / total assets
      C = EBIT / total assets  (operating_profit is used as a proxy)
      D = market value of equity / total liabilities — book equity is
          used as a proxy here (this is the Z'' variant convention).
      E = revenue / total assets

    Returns ``None`` unless every component is present and total assets
    and total liabilities are non-zero.
    """
    if l.total_assets is None or l.total_assets == 0:
        return None
    if l.total_liabilities is None or l.total_liabilities == 0:
        return None
    wc = (
        (l.current_assets - l.current_liabilities)
        if l.current_assets is not None and l.current_liabilities is not None
        else None
    )
    ebit = l.ebit if l.ebit is not None else l.operating_profit
    if (
        wc is None
        or l.retained_earnings is None
        or ebit is None
        or l.equity is None
        or l.revenue is None
    ):
        return None
    a = wc / l.total_assets
    b = l.retained_earnings / l.total_assets
    c = ebit / l.total_assets
    d = l.equity / l.total_liabilities
    e = l.revenue / l.total_assets
    return 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e
