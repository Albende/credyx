from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ma import MAAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_ompic():
    adapter = MAAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MA"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
    assert health.capabilities["financials"] is True


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = MAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Maroc Telecom", limit=5)


@pytest.mark.asyncio
async def test_lookup_invalid_ice_format_raises():
    adapter = MAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345")


@pytest.mark.asyncio
async def test_lookup_rc_raises_not_implemented():
    adapter = MAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "Casablanca 123456"
        )


@pytest.mark.asyncio
async def test_lookup_unsupported_identifier_raises():
    adapter = MAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "529900T8BM49AURSDO55")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_maroc_telecom_best_effort():
    """Maroc Telecom (Itissalat Al-Maghrib) — ICE 001525713000050.

    The DGI page is not a stable JSON API. We accept either a real
    identity match or `AdapterNotImplementedError` (which is the spec'd
    behaviour when no free machine-readable identity is available).
    """
    adapter = MAAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.VAT, "001525713000050"
        )
    except AdapterNotImplementedError:
        return
    if details is None:
        return
    assert details.country == "MA"
    assert details.identifiers
    assert details.identifiers[0].value == "001525713000050"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_non_listed_returns_empty():
    """Non-listed companies have no free public filings; expect [] not 501."""
    adapter = MAAdapter()
    # OCP Group is state-owned but its annual reports are on
    # ocpgroup.ma, not AMMC's listed-issuer feed.
    filings = await adapter.fetch_financials("000000067000049", years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_id():
    adapter = MAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("RC-12345", years=3)
