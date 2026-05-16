"""Industry-benchmark lookup for the risk engine.

The risk engine compares a company's deterministic ratios against
median / p25 / p75 bands published by BACH (Bank for the Accounts of
Companies Harmonised — ECB / ECCBSO public dataset). The data lives in
``packages/risk/data/nace_benchmarks.json`` and is keyed by NACE Rev. 2
2-digit section code.

The lookup is intentionally narrow: given a NACE code (any length), it
reduces to the 2-digit prefix and returns the benchmark or ``None``. We
never fabricate a benchmark for an unknown industry.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from packages.shared.models import FinancialRatios

_DATA_PATH = Path(__file__).parent / "data" / "nace_benchmarks.json"

# Ratio fields we compare. Must match attribute names on FinancialRatios.
COMPARABLE_RATIOS: tuple[str, ...] = (
    "current_ratio",
    "quick_ratio",
    "debt_to_equity",
    "debt_to_assets",
    "roe",
    "roa",
    "gross_margin",
    "net_margin",
    "altman_z_score",
)


class RatioBand(BaseModel):
    """A single ratio's median + interquartile band."""

    median: float
    p25: float
    p75: float


class IndustryBenchmark(BaseModel):
    """Median ratios for one NACE 2-digit industry."""

    nace_code: str
    name: str
    source: str
    median_ratios: dict[str, dict[str, float]] = Field(default_factory=dict)

    def band(self, ratio_name: str) -> RatioBand | None:
        raw = self.median_ratios.get(ratio_name)
        if not raw:
            return None
        try:
            return RatioBand(median=raw["median"], p25=raw["p25"], p75=raw["p75"])
        except (KeyError, TypeError):
            return None


@lru_cache(maxsize=1)
def load_benchmarks() -> dict[str, IndustryBenchmark]:
    """Load and cache ``nace_benchmarks.json`` keyed by 2-digit NACE code."""
    payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    out: dict[str, IndustryBenchmark] = {}
    for key, entry in payload.items():
        if key.startswith("_"):
            continue
        out[key] = IndustryBenchmark(**entry)
    return out


def _normalize_nace(code: str) -> str | None:
    """Strip dots / whitespace and return the first two digits, or None."""
    if not code:
        return None
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) < 2:
        return None
    return digits[:2]


def benchmark_for(nace_code: str | None) -> IndustryBenchmark | None:
    """Return the most-specific benchmark for a NACE code.

    Accepts 2-, 3-, or 4-digit codes (with or without dots). Reduces to the
    2-digit section and looks it up. Returns ``None`` if the input is
    missing or the section is not in our table — we never fabricate.
    """
    if nace_code is None:
        return None
    two = _normalize_nace(nace_code)
    if two is None:
        return None
    return load_benchmarks().get(two)


def _classify(value: float | None, band: RatioBand | None) -> str:
    if value is None or band is None:
        return "unknown"
    if value > band.p75:
        return "above_p75"
    if value < band.p25:
        return "below_p25"
    return "median_band"


def compare(
    ratios: FinancialRatios, benchmark: IndustryBenchmark
) -> dict[str, str]:
    """Classify each comparable ratio against the industry band.

    Returns a mapping of ratio name -> one of ``above_p75``, ``median_band``,
    ``below_p25``, ``unknown``.
    """
    result: dict[str, str] = {}
    for ratio_name in COMPARABLE_RATIOS:
        value = getattr(ratios, ratio_name, None)
        band = benchmark.band(ratio_name)
        result[ratio_name] = _classify(value, band)
    return result
