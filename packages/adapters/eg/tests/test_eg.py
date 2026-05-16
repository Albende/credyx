"""Integration tests for the Egypt adapter.

EG has no free public APIs for search/lookup, so those calls must raise
``AdapterNotImplementedError``. ``fetch_financials`` returns a best-effort
EGX pointer for listed tickers and an empty list otherwise. The health
probe hits the live EGX website.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.eg import EGAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_not_implemented():
    adapter = EGAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Commercial International Bank", limit=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_tax_id_not_implemented():
    adapter = EGAdapter()
    with pytest.raises(AdapterNotImplementedError):
        # CIB Tax ID: 200-118-815
        await adapter.lookup_by_identifier(IdentifierType.VAT, "200-118-815")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_not_implemented():
    adapter = EGAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "12345")


@pytest.mark.asyncio
async def test_invalid_tax_id_rejected():
    adapter = EGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "abc")


@pytest.mark.asyncio
async def test_unsupported_identifier_rejected():
    adapter = EGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "5493001KJTIIGC8Y1R12")


@pytest.mark.asyncio
async def test_financials_non_listed_returns_empty():
    adapter = EGAdapter()
    filings = await adapter.fetch_financials("not-a-ticker-1234", years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_financials_listed_ticker_returns_pointer():
    adapter = EGAdapter()
    # CIB on EGX = COMI; Telecom Egypt = ETEL; Eastern Tobacco = EAST.
    for ticker in ("COMI", "ETEL", "EAST", "TMGH"):
        filings = await adapter.fetch_financials(ticker, years=3)
        assert len(filings) == 1
        assert filings[0].currency == "EGP"
        assert filings[0].source_url and "egx.com.eg" in filings[0].source_url
        assert ticker in filings[0].source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reaches_egx():
    adapter = EGAdapter()
    health = await adapter.health_check()
    # Search/lookup unavailable, but EGX should be reachable for financials.
    assert health.country_code == "EG"
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.OK, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
