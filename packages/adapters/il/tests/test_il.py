from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.il import ILAdapter
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = ILAdapter()
    health = await adapter.health_check()
    assert health.country_code == "IL"
    assert health.status.value in {"ok", "degraded"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_teva():
    adapter = ILAdapter()
    matches = await adapter.search_by_name("Teva", limit=10)
    assert matches, "Expected at least one match for 'Teva' on data.gov.il"
    assert any("teva" in m.name.lower() for m in matches)
    assert all(m.country == "IL" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_teva_by_company_number():
    adapter = ILAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "520013954"
    )
    assert details is not None
    assert details.id == "520013954"
    assert details.country == "IL"
    assert any(
        ident.type == IdentifierType.VAT and ident.value == "520013954"
        for ident in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bank_hapoalim_by_vat_alias():
    adapter = ILAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "520000118"
    )
    assert details is not None
    assert details.id == "520000118"


@pytest.mark.asyncio
async def test_invalid_identifier_rejected():
    adapter = ILAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "12345"
        )


@pytest.mark.asyncio
async def test_unsupported_identifier_type_rejected():
    adapter = ILAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.SIREN, "520013954")


@pytest.mark.asyncio
async def test_fetch_financials_empty_for_now():
    adapter = ILAdapter()
    filings = await adapter.fetch_financials("520013954")
    assert filings == []
