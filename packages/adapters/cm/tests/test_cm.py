from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.cm import CMAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = CMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("SOCAPALM")


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented():
    adapter = CMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "RC/DLA/1968/B/1234"
        )


@pytest.mark.asyncio
async def test_fetch_financials_unknown_returns_empty():
    adapter = CMAdapter()
    filings = await adapter.fetch_financials("not-a-listed-company")
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_known_issuer_returns_pointer():
    adapter = CMAdapter()
    filings = await adapter.fetch_financials("SAFACAM")
    assert len(filings) == 1
    assert filings[0].currency == "XAF"
    assert filings[0].source_url and "bvm-ac.com" in filings[0].source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_bvmac():
    adapter = CMAdapter()
    health = await adapter.health_check()
    # Site is reachable → DEGRADED (no search/lookup); unreachable → ERROR.
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
