from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.zm import ZMAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = ZMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Zambia National Commercial Bank")


@pytest.mark.asyncio
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = ZMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "123456")


@pytest.mark.asyncio
async def test_lookup_by_tpin_raises_not_implemented():
    adapter = ZMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "1000000000")


@pytest.mark.asyncio
async def test_fetch_financials_unknown_ticker_returns_empty():
    adapter = ZMAdapter()
    assert await adapter.fetch_financials("UNKNOWN") == []


@pytest.mark.asyncio
async def test_fetch_financials_known_ticker_returns_list():
    adapter = ZMAdapter()
    # Known LuSE tickers are accepted; per-PDF crawling is not yet wired
    # so the contract is "list, possibly empty" — never invented filings.
    for ticker in ("ZANACO", "CEC", "LAFA"):
        result = await adapter.fetch_financials(ticker)
        assert isinstance(result, list)


def test_adapter_metadata():
    adapter = ZMAdapter()
    assert adapter.country_code == "ZM"
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_luse():
    adapter = ZMAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ZM"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED, AdapterStatus.ERROR}
