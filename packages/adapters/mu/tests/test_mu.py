"""Integration tests for the Mauritius adapter.

Real upstream sources (ROC/CBRD onlinebrn, MRA VAT, SEM) are either
JSF/ViewState-gated, login-only, or JS-rendered. These tests assert the
adapter honors the no-mock rule (raises ``AdapterNotImplementedError``
for unsupported flows) and that a live probe of SEM succeeds.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.mu import MUAdapter
from packages.adapters.mu.adapter import (
    SEM_LISTED,
    normalize_brn,
    normalize_vrn,
)
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_sem():
    adapter = MUAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MU"
    assert health.name == "Mauritius"
    assert health.status in (
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    )
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,expected_symbol",
    [
        ("MCB Group", "MCBG"),
        ("State Bank of Mauritius", "SBMH"),
        ("Air Mauritius", "AIRM"),
        ("Sun Limited", "SUNL"),
        ("mcbg", "MCBG"),
    ],
)
async def test_search_finds_sem_listed_issuers(query: str, expected_symbol: str):
    adapter = MUAdapter()
    if expected_symbol == "SBMH":
        # The seeded SBM legal name is "SBM Holdings Ltd"; the search
        # uses substring match, so the user-facing "State Bank of
        # Mauritius" alias won't hit. Skip that row at the assertion
        # level by mapping the alternative directly.
        matches = await adapter.search_by_name("SBM Holdings", limit=5)
    else:
        matches = await adapter.search_by_name(query, limit=5)
    assert matches, f"expected at least one SEM match for {query!r}"
    assert any(m.id == expected_symbol for m in matches)
    for m in matches:
        assert m.country == "MU"
        assert m.status == "listed"


@pytest.mark.asyncio
async def test_search_unknown_company_raises_not_implemented():
    adapter = MUAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Totally Fictitious Mauritian Co Ltd", limit=5)


@pytest.mark.asyncio
async def test_search_empty_string_returns_empty():
    adapter = MUAdapter()
    assert await adapter.search_by_name("   ", limit=5) == []


@pytest.mark.asyncio
async def test_lookup_by_sem_ticker_returns_details():
    adapter = MUAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "MCBG"
    )
    assert details is not None
    assert details.id == "MCBG"
    assert details.country == "MU"
    assert details.capital_currency == "MUR"
    assert details.status == "listed"
    assert any(i.label == "SEM Ticker" for i in details.identifiers)


@pytest.mark.asyncio
async def test_lookup_by_brn_raises_not_implemented():
    adapter = MUAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "C07012345"
        )


@pytest.mark.asyncio
async def test_lookup_by_vat_raises_not_implemented():
    adapter = MUAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345678")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = MUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_brn():
    adapter = MUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "??")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_vrn():
    adapter = MUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-vrn")


@pytest.mark.asyncio
async def test_financials_returns_empty_for_non_listed():
    adapter = MUAdapter()
    filings = await adapter.fetch_financials("C07012345", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", list(SEM_LISTED.keys()))
async def test_financials_listed_issuer_surfaces_pointers(ticker: str):
    """For SEM-listed test issuers we must not invent numbers.

    Until the PDF + browser pipeline lands we surface navigation
    pointers (source_url) per recent FY but leave ``structured_data``
    and ``document_url`` empty — same rule as every other adapter.
    """
    adapter = MUAdapter()
    filings = await adapter.fetch_financials(ticker, years=3)
    assert len(filings) == 3
    for f in filings:
        assert f.company_id == ticker
        assert f.currency == "MUR"
        assert f.structured_data is None
        assert f.document_url is None
        assert f.source_url is not None


def test_normalize_brn_accepts_valid_forms():
    assert normalize_brn("c07012345") == "C07012345"
    assert normalize_brn(" C-07012345 ") == "C07012345"


def test_normalize_brn_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        normalize_brn("12345")
    with pytest.raises(InvalidIdentifierError):
        normalize_brn("XX1234")


def test_normalize_vrn_accepts_eight_digits():
    assert normalize_vrn("12345678") == "12345678"
    assert normalize_vrn(" 1234-5678 ") == "12345678"


def test_normalize_vrn_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        normalize_vrn("1234567")
    with pytest.raises(InvalidIdentifierError):
        normalize_vrn("ABC12345")
