from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.bw import BWAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = BWAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Sefalana", limit=5)


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented():
    adapter = BWAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "CO12345")


@pytest.mark.asyncio
async def test_financials_unknown_ticker_returns_empty():
    adapter = BWAdapter()
    assert await adapter.fetch_financials("UNKNOWN_TICKER") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["FNBB", "SEFA", "CHOP", "LHL"])
async def test_financials_listed_ticker_returns_bse_pointer(ticker: str):
    adapter = BWAdapter()
    filings = await adapter.fetch_financials(ticker)
    assert len(filings) == 1
    f = filings[0]
    assert f.company_id == ticker
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "BWP"
    assert f.source_url is not None and "bse.co.bw" in f.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_bse():
    adapter = BWAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BW"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
