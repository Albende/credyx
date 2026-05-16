from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.bo import BOAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_search_not_implemented():
    adapter = BOAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("YPFB")


@pytest.mark.asyncio
async def test_lookup_not_implemented():
    adapter = BOAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "1020601022")


@pytest.mark.asyncio
async def test_lookup_invalid_identifier_type():
    adapter = BOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "anything")


@pytest.mark.asyncio
async def test_fetch_financials_returns_bbv_pointers():
    adapter = BOAdapter()
    filings = await adapter.fetch_financials("1020601022", years=3)
    assert len(filings) == 3
    assert all(f.currency == "BOB" for f in filings)
    assert all(f.type == FilingType.ANNUAL_REPORT for f in filings)
    assert all("bbv.com.bo" in (f.source_url or "") for f in filings)
    # No fabricated line items — structured data must stay null.
    assert all(f.structured_data is None for f in filings)


@pytest.mark.asyncio
async def test_fetch_financials_empty_id_returns_nothing():
    adapter = BOAdapter()
    assert await adapter.fetch_financials("") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_bbv():
    adapter = BOAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BO"
    assert health.status in (
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    )
