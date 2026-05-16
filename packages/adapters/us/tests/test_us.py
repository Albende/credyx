"""Tests for the US (SEC EDGAR) adapter.

Integration tests hit real SEC endpoints and are gated behind the
`integration` marker. The mock tests below exercise the XBRL flattening
logic in isolation.
"""
from __future__ import annotations

import pytest

from packages.adapters.us import USAdapter
from packages.adapters.us.adapter import _build_structured_by_year
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_apple():
    adapter = USAdapter()
    matches = await adapter.search_by_name("Apple Inc.", limit=5)
    assert any("apple" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_apple_cik():
    adapter = USAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.CIK, "0000320193")
    assert details is not None
    assert "apple" in details.name.lower()
    assert any(i.type == IdentifierType.CIK for i in details.identifiers)


def test_build_structured_by_year_from_fake_facts():
    """Synthetic companyfacts JSON: ensures the FY 10-K extraction picks
    the latest restated value and assembles the schema the risk engine
    expects."""
    facts = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 100,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            },
                            # Restated value, filed later — should win.
                            {
                                "end": "2023-12-31",
                                "val": 110,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            },
                            # Different fiscal year.
                            {
                                "end": "2022-12-31",
                                "val": 90,
                                "fy": 2022,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-02-01",
                            },
                            # Quarterly data — must be ignored.
                            {
                                "end": "2023-09-30",
                                "val": 95,
                                "fy": 2023,
                                "fp": "Q3",
                                "form": "10-Q",
                                "filed": "2023-10-15",
                            },
                        ]
                    }
                },
                "Liabilities": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 60,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 50,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 200,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 25,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 30,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
            }
        }
    }

    out = _build_structured_by_year(facts)
    assert 2023 in out
    payload = out[2023]
    assert payload["currency"] == "USD"
    assert payload["period_end"] == "2023-12-31"
    assert payload["consolidated"] is True
    # Restated value wins.
    assert payload["balance_sheet"]["total_assets"] == 110
    assert payload["balance_sheet"]["total_liabilities"] == 60
    assert payload["balance_sheet"]["equity"] == 50
    assert payload["income_statement"]["revenue"] == 200
    assert payload["income_statement"]["net_income"] == 25
    assert payload["cash_flow"]["operating_cf"] == 30
    # raw_concepts mirrors the source tag names.
    assert payload["raw_concepts"]["Assets"] == 110
    assert (
        payload["raw_concepts"]["RevenueFromContractWithCustomerExcludingAssessedTax"]
        == 200
    )
    # Prior year present from Assets fact even when most lines are missing.
    assert 2022 in out
    assert out[2022]["balance_sheet"]["total_assets"] == 90


def test_build_structured_skips_missing_concepts():
    facts = {"facts": {"us-gaap": {}}}
    assert _build_structured_by_year(facts) == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_financials_apple_have_xbrl():
    adapter = USAdapter()
    filings = await adapter.fetch_financials("0000320193", years=5)
    assert filings, "expected at least one Apple 10-K filing"

    fully_populated = [
        f
        for f in filings
        if f.structured_data
        and f.structured_data.get("balance_sheet", {}).get("total_assets") is not None
        and f.structured_data.get("income_statement", {}).get("net_income") is not None
    ]
    assert len(fully_populated) >= 3, (
        "expected >=3 recent Apple filings with both total_assets and net_income, "
        f"got {len(fully_populated)} out of {len(filings)}"
    )

    sample = fully_populated[0].structured_data
    assert sample["currency"] == "USD"
    assert "raw_concepts" in sample
    assert sample["balance_sheet"]["total_assets"] > 0
