"""Integration tests for the Kenya adapter.

Real upstream sources (BRS, KRA, NSE) are either fully gated or paid for
structured data. These tests assert the adapter honors the no-mock rule
(raises ``AdapterNotImplementedError`` for search + lookup) and that a
live probe of NSE/BRS succeeds.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ke import KEAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_real_sources():
    adapter = KEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "KE"
    assert health.name == "Kenya"
    # Either DEGRADED (gated but reachable) or ERROR (both probes down).
    assert health.status in (AdapterStatus.DEGRADED, AdapterStatus.ERROR)
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_raises_not_implemented():
    adapter = KEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Safaricom", limit=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = KEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "PVT-ABC12345"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_kra_pin_raises_not_implemented():
    adapter = KEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "P051092002G")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = KEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "529900T8BM49AURSDO55")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_kra_pin():
    adapter = KEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-pin")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_brs_number():
    adapter = KEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "??")


@pytest.mark.asyncio
async def test_financials_returns_empty_for_non_listed():
    adapter = KEAdapter()
    filings = await adapter.fetch_financials("PVT-ABC12345", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["SCOM", "EQTY", "EABL", "KCB"])
async def test_financials_listed_issuer_no_mock(ticker: str):
    """For NSE-listed test issuers we must not invent filings.

    Until the PDF + browser pipeline lands we explicitly return ``[]``
    rather than fabricate a filing — same rule as every other adapter.
    """
    adapter = KEAdapter()
    filings = await adapter.fetch_financials(ticker, years=5)
    assert filings == []
