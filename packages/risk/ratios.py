"""Pure-function financial ratio extraction.

Adapters can return `structured_data` in heterogeneous shapes. This module
normalizes the common line items and computes a stable set of ratios for the
LLM. Anything we can't extract becomes `None` — never zero, never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    current_assets: float | None = None
    cash: float | None = None
    inventory: float | None = None
    receivables: float | None = None
    total_assets: float | None = None
    current_liabilities: float | None = None
    total_liabilities: float | None = None
    long_term_debt: float | None = None
    equity: float | None = None
    retained_earnings: float | None = None


# Common keys across registries. Keys are normalized lowercase no-spaces.
_LINE_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "revenue", "turnover", "salesrevenue", "totalrevenue", "netsales",
        "totalnetsales", "operatingrevenue", "totaloperatingrevenue",
    ],
    "cost_of_sales": ["costofsales", "costofrevenue", "costofgoodssold", "cogs"],
    "gross_profit": ["grossprofit"],
    "operating_profit": ["operatingprofit", "operatingincome", "ebit"],
    "net_income": ["netincome", "profitfortheyear", "netprofit", "profitloss"],
    "current_assets": ["currentassets", "totalcurrentassets"],
    "cash": ["cash", "cashandcashequivalents"],
    "inventory": ["inventory", "inventories"],
    "receivables": ["receivables", "tradereceivables", "accountsreceivable"],
    "total_assets": ["totalassets", "assets"],
    "current_liabilities": ["currentliabilities", "totalcurrentliabilities"],
    "total_liabilities": ["totalliabilities", "liabilities"],
    "long_term_debt": ["longtermdebt", "noncurrentdebt", "longtermborrowings"],
    "equity": ["totalequity", "equity", "stockholdersequity", "shareholdersequity"],
    "retained_earnings": ["retainedearnings"],
}


def _normalize_key(k: str) -> str:
    return "".join(ch for ch in k.lower() if ch.isalnum())


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _coerce_number(v: Any) -> float | None:
    if v is None:
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


def extract_financial_lines(filing: FinancialFiling) -> FinancialLines | None:
    """Pull a FinancialLines record from a filing's structured_data, if any."""
    if not filing.structured_data:
        return None
    flat = _flatten(filing.structured_data)
    norm = {_normalize_key(k.split(".")[-1]): _coerce_number(v) for k, v in flat.items()}

    out = FinancialLines(year=filing.year)
    for field, aliases in _LINE_ALIASES.items():
        for alias in aliases:
            if alias in norm and norm[alias] is not None:
                setattr(out, field, norm[alias])
                break

    if out.gross_profit is None and out.revenue is not None and out.cost_of_sales is not None:
        out.gross_profit = out.revenue - out.cost_of_sales
    if out.ebit is None and out.operating_profit is not None:
        out.ebit = out.operating_profit
    return out


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def compute_ratios(filings: list[FinancialFiling]) -> list[FinancialRatios]:
    """Compute deterministic ratios per year from the available filings."""
    by_year: dict[int, FinancialLines] = {}
    for f in filings:
        lines = extract_financial_lines(f)
        if lines is None:
            continue
        existing = by_year.get(f.year)
        if existing is None:
            by_year[f.year] = lines
        else:
            for fname in lines.__dataclass_fields__:
                if getattr(existing, fname) is None:
                    setattr(existing, fname, getattr(lines, fname))

    results: list[FinancialRatios] = []
    for year in sorted(by_year.keys(), reverse=True):
        l = by_year[year]
        prev = by_year.get(year - 1)
        ratios = FinancialRatios(
            year=year,
            current_ratio=_safe_div(l.current_assets, l.current_liabilities),
            quick_ratio=_safe_div(
                (l.current_assets or 0) - (l.inventory or 0)
                if l.current_assets is not None
                else None,
                l.current_liabilities,
            ),
            debt_to_equity=_safe_div(l.total_liabilities, l.equity),
            debt_to_assets=_safe_div(l.total_liabilities, l.total_assets),
            roe=_safe_div(l.net_income, l.equity),
            roa=_safe_div(l.net_income, l.total_assets),
            gross_margin=_safe_div(l.gross_profit, l.revenue),
            net_margin=_safe_div(l.net_income, l.revenue),
            working_capital=(
                l.current_assets - l.current_liabilities
                if l.current_assets is not None and l.current_liabilities is not None
                else None
            ),
            altman_z_score=_altman_z(l),
            revenue_growth_yoy=(
                _safe_div(
                    (l.revenue - prev.revenue)
                    if l.revenue is not None and prev and prev.revenue is not None
                    else None,
                    prev.revenue if prev else None,
                )
            ),
        )
        results.append(ratios)
    return results


def _altman_z(l: FinancialLines) -> float | None:
    """Altman Z-score for public manufacturers (the classic 1968 form).

    Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
    where:
      A = working capital / total assets
      B = retained earnings / total assets
      C = EBIT / total assets
      D = market value of equity / total liabilities  (we use book equity as proxy)
      E = revenue / total assets

    Returns None unless all components are present.
    """
    if l.total_assets in (None, 0):
        return None
    wc = (
        (l.current_assets - l.current_liabilities)
        if l.current_assets is not None and l.current_liabilities is not None
        else None
    )
    if wc is None or l.retained_earnings is None or l.ebit is None or l.equity is None or l.total_liabilities in (None, 0) or l.revenue is None:
        return None
    a = wc / l.total_assets
    b = l.retained_earnings / l.total_assets
    c = l.ebit / l.total_assets
    d = l.equity / l.total_liabilities
    e = l.revenue / l.total_assets
    return 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e
