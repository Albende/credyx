from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.kw import KWAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = KWAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("National Bank of Kuwait")


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented():
    adapter = KWAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "12345")


def test_adapter_metadata():
    adapter = KWAdapter()
    assert adapter.country_code == "KW"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_boursa():
    adapter = KWAdapter()
    health = await adapter.health_check()
    assert health.country_code == "KW"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED, AdapterStatus.ERROR}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_pointer_for_nbk():
    adapter = KWAdapter()
    filings = await adapter.fetch_financials("NBK")
    # Either Boursa is reachable (returns 1 pointer) or unreachable ([]) —
    # never invented data.
    assert isinstance(filings, list)
    for f in filings:
        assert f.company_id == "NBK"
        assert f.currency == "KWD"
        assert f.source_url and "boursakuwait" in f.source_url
