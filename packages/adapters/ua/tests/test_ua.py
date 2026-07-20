from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ua import UAAdapter
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_naftogaz():
    adapter = UAAdapter()
    matches = await adapter.search_by_name("Naftogaz", limit=5)
    # Clarity returns registry names in Ukrainian Cyrillic.
    assert any(
        m.id == "20077720" or "нафтогаз" in m.name.lower() for m in matches
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_naftogaz_by_edrpou():
    adapter = UAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "20077720"
    )
    assert details is not None
    assert details.country == "UA"
    assert details.id == "20077720"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_privatbank_via_vat_prefix():
    adapter = UAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "UA143605700000"
    )
    assert details is not None
    assert details.id == "14360570"


@pytest.mark.asyncio
async def test_lookup_rejects_non_supported_identifier():
    adapter = UAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "XXX")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_edrpou():
    adapter = UAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "not-a-number"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_empty_for_non_issuer():
    adapter = UAAdapter()
    filings = await adapter.fetch_financials("00000000")
    assert filings == []
