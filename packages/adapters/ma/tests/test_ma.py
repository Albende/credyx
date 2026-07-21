from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ma import MAAdapter
from packages.shared.models import AdapterStatus, IdentifierType

MAROC_TELECOM_LEI = "254900LH0G1ZIZ78Y462"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_gleif():
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
async def test_search_by_name_rejects_empty():
    adapter = MAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.search_by_name("   ", limit=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_gleif_matches():
    adapter = MAAdapter()
    matches = await adapter.search_by_name("Itissalat", limit=5)
    assert matches
    top = matches[0]
    assert top.country == "MA"
    assert top.id == MAROC_TELECOM_LEI
    assert any(i.type == IdentifierType.LEI for i in top.identifiers)


@pytest.mark.asyncio
async def test_lookup_invalid_lei_format_raises():
    adapter = MAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "12345")


@pytest.mark.asyncio
async def test_lookup_ice_raises_not_implemented():
    adapter = MAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "001525713000050")


@pytest.mark.asyncio
async def test_lookup_rc_raises_not_implemented():
    adapter = MAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "Casablanca 123456"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_maroc_telecom_by_lei():
    adapter = MAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.LEI, MAROC_TELECOM_LEI
    )
    assert details is not None
    assert details.country == "MA"
    assert details.id == MAROC_TELECOM_LEI
    assert "maghrib" in details.name.lower()
    assert any(i.type == IdentifierType.COMPANY_NUMBER for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_maroc_telecom_returns_annual_reports():
    adapter = MAAdapter()
    filings = await adapter.fetch_financials(MAROC_TELECOM_LEI, years=3)
    assert filings
    first = filings[0]
    assert first.company_id == MAROC_TELECOM_LEI
    assert first.currency == "MAD"
    assert first.document_url and first.document_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_non_filing_company_returns_empty():
    """A valid Moroccan LEI that does not file with the AMF has no filings."""
    adapter = MAAdapter()
    # OCP S.A. is not admitted on Euronext Paris, so it has no AMF feed.
    filings = await adapter.fetch_financials("213800D26TAPVTCVWG40", years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_ice_returns_empty():
    """A 15-digit ICE is not resolvable to filings without paid OMPIC access."""
    adapter = MAAdapter()
    assert await adapter.fetch_financials("000000067000049", years=3) == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_id():
    adapter = MAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("RC-12345", years=3)
