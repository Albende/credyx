"""Integration tests for the Slovenia (AJPES) adapter.

These tests hit real AJPES endpoints. Marked `integration` so CI can opt-out
with `-m "not integration"`. The real public matična for Krka, d. d. is
5043611000 (the 5043591000 sometimes seen elsewhere is a typo).
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.si import SIAdapter
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_krka():
    adapter = SIAdapter()
    matches = await adapter.search_by_name("Krka", limit=10)
    assert matches, "expected at least one match for Krka"
    assert any("krka" in m.name.lower() for m in matches)
    krka = next(m for m in matches if "krka" in m.name.lower() and "zdravil" in m.name.lower())
    assert krka.id == "5043611000"
    id_types = {i.type for i in krka.identifiers}
    assert IdentifierType.COMPANY_NUMBER in id_types
    assert IdentifierType.VAT in id_types


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_maticna_krka():
    adapter = SIAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "5043611000"
    )
    assert details is not None
    assert "krka" in details.name.lower()
    assert details.country == "SI"
    id_types = {i.type for i in details.identifiers}
    assert IdentifierType.COMPANY_NUMBER in id_types
    assert IdentifierType.VAT in id_types
    vat = next(i for i in details.identifiers if i.type == IdentifierType.VAT)
    assert vat.value == "SI82646716"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_petrol():
    adapter = SIAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "SI80267432")
    assert details is not None
    assert "petrol" in details.name.lower()
    assert details.id == "5025796000"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_returns_address_from_jolp():
    adapter = SIAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "5043611000"
    )
    assert details is not None
    # JOLP returns an address — if it stops returning one for active firms
    # something has broken.
    assert details.registered_address
    assert "Novo mesto" in (details.registered_address or "")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    adapter = SIAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "9999999999"
    )
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_krka_from_seonet():
    adapter = SIAdapter()
    filings = await adapter.fetch_financials("5043611000", years=3)
    assert filings, "expected Krka (a listed issuer) to have SEOnet filings"
    for f in filings:
        assert f.company_id == "5043611000"
        assert f.currency == "EUR"
        assert f.source_url and "seonet.ljse.si" in f.source_url
        assert f.document_url and "AttachmentID=" in f.document_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_private_company_not_implemented():
    # A private (non-listed) company has no public filings on SEOnet.
    adapter = SIAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.fetch_financials("8980870000", years=3)
