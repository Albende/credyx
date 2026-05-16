from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.bh import BHAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = BHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Bahrain Telecommunications Company")


@pytest.mark.asyncio
async def test_lookup_company_number_raises_not_implemented():
    adapter = BHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "12345")


@pytest.mark.asyncio
async def test_lookup_vat_raises_not_implemented():
    adapter = BHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "200000000000002")


def test_adapter_metadata():
    adapter = BHAdapter()
    assert adapter.country_code == "BH"
    assert adapter.country_name == "Bahrain"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_fetch_financials_empty_ticker_returns_empty():
    adapter = BHAdapter()
    assert await adapter.fetch_financials("") == []
    assert await adapter.fetch_financials("   ") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_bahrain_bourse():
    adapter = BHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BH"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("ticker", ["BATELCO", "AUB", "ALBH", "GFH"])
async def test_fetch_financials_returns_pointer_for_listed_issuers(ticker: str):
    adapter = BHAdapter()
    filings = await adapter.fetch_financials(ticker)
    # Either Bahrain Bourse is reachable (pointer returned) or it is not
    # ([]). We never invent rows.
    assert isinstance(filings, list)
    for f in filings:
        assert f.company_id == ticker
        assert f.currency == "BHD"
        assert f.source_url and "bahrainbourse.com" in f.source_url
