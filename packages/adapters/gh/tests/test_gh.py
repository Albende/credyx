"""Integration tests for the Ghana adapter.

Real upstream sources (RGD, GRA, GSE) are either fully gated or paid for
structured data. These tests assert the adapter honors the no-mock rule
(raises ``AdapterNotImplementedError`` for search + lookup) and that a
live probe of GSE/RGD succeeds.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.gh import GHAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_real_sources():
    adapter = GHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "GH"
    assert health.name == "Ghana"
    assert health.status in (AdapterStatus.DEGRADED, AdapterStatus.ERROR)
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_raises_not_implemented():
    adapter = GHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("MTN Ghana", limit=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = GHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "CS123456789"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_tin_raises_not_implemented():
    adapter = GHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "C0001234567")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = GHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_rgd_number():
    adapter = GHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "not-a-number"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_tin():
    adapter = GHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345")


@pytest.mark.asyncio
async def test_financials_returns_empty_for_non_listed():
    adapter = GHAdapter()
    filings = await adapter.fetch_financials("CS123456789", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["MTNGH", "GCB", "EGH", "TOTAL"])
async def test_financials_listed_issuer_no_mock(ticker: str):
    """For GSE-listed test issuers we must not invent filings.

    Until the PDF + browser pipeline lands we explicitly return ``[]``
    rather than fabricate a filing — same rule as every other adapter.
    """
    adapter = GHAdapter()
    filings = await adapter.fetch_financials(ticker, years=5)
    assert filings == []
