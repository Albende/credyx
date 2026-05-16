from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.ci import CIAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = CIAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Sonatel", limit=5)


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented():
    adapter = CIAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "CI-ABJ-2010-B-12345"
        )


@pytest.mark.asyncio
async def test_lookup_by_vat_also_raises_not_implemented():
    adapter = CIAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "0123456A")


@pytest.mark.asyncio
async def test_financials_unknown_ticker_returns_empty():
    adapter = CIAdapter()
    assert await adapter.fetch_financials("UNKNOWN_TICKER") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["SNTS", "BOAC", "ETIT", "SLBC"])
async def test_financials_listed_ticker_returns_brvm_pointer(ticker: str):
    adapter = CIAdapter()
    filings = await adapter.fetch_financials(ticker)
    assert len(filings) == 1
    f = filings[0]
    assert f.company_id == ticker
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "XOF"
    assert f.document_format == "html"
    assert f.source_url is not None and "brvm.org" in f.source_url


@pytest.mark.asyncio
async def test_financials_ticker_is_case_insensitive():
    adapter = CIAdapter()
    filings = await adapter.fetch_financials("snts")
    assert len(filings) == 1
    assert filings[0].company_id == "SNTS"


@pytest.mark.asyncio
async def test_adapter_metadata():
    adapter = CIAdapter()
    assert adapter.country_code == "CI"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_brvm():
    adapter = CIAdapter()
    health = await adapter.health_check()
    assert health.country_code == "CI"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
