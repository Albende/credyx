from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.bo import BOAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType

# Banco Mercantil Santa Cruz S.A. — active BBV-listed issuer, stable test entity.
BMSC_MATRICULA = "1020557029"


@pytest.mark.asyncio
async def test_lookup_invalid_identifier_type():
    adapter = BOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "anything")


@pytest.mark.asyncio
async def test_search_empty_query_returns_nothing():
    adapter = BOAdapter()
    assert await adapter.search_by_name("") == []


@pytest.mark.asyncio
async def test_fetch_financials_empty_id_returns_nothing():
    adapter = BOAdapter()
    assert await adapter.fetch_financials("") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_live():
    adapter = BOAdapter()
    matches = await adapter.search_by_name("BANCO MERCANTIL", limit=5)
    assert matches
    assert any("MERCANTIL" in m.name.upper() for m in matches)
    assert all(m.country == "BO" and m.id for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_identifier_live():
    adapter = BOAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, BMSC_MATRICULA)
    assert details is not None
    assert "MERCANTIL" in details.name.upper()
    assert details.legal_form
    assert details.registered_address
    assert any(i.value == BMSC_MATRICULA for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_live():
    adapter = BOAdapter()
    filings = await adapter.fetch_financials(BMSC_MATRICULA, years=3)
    assert filings
    assert all(f.currency == "BOB" for f in filings)
    assert all(f.type == FilingType.ANNUAL_REPORT for f in filings)
    assert all(f.source_url and "seprec.gob.bo" in f.source_url for f in filings)
    # No fabricated line items and no undownloadable document URL.
    assert all(f.structured_data is None for f in filings)
    assert all(f.document_url is None for f in filings)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_seprec():
    adapter = BOAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BO"
    assert health.status in (
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    )
