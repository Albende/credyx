from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.cd import CDAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = CDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name(
            "Société Commerciale des Transports et des Ports"
        )


@pytest.mark.asyncio
async def test_lookup_by_rccm_raises_not_implemented():
    adapter = CDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "CD/KIN/RCCM/14-B-1234"
        )


@pytest.mark.asyncio
async def test_lookup_by_nif_raises_not_implemented():
    adapter = CDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "A0801234X")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = CDAdapter()
    filings = await adapter.fetch_financials("BIAC")
    assert filings == []


@pytest.mark.asyncio
async def test_adapter_metadata():
    adapter = CDAdapter()
    assert adapter.country_code == "CD"
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.primary_identifier is IdentifierType.COMPANY_NUMBER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_guichet_unique():
    adapter = CDAdapter()
    health = await adapter.health_check()
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
    assert health.capabilities["financials"] is False
