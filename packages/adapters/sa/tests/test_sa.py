from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.sa import SAAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_cr_normalizer_rejects_short():
    adapter = SAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "12345")


@pytest.mark.asyncio
async def test_vat_valid_normalizes_then_not_implemented():
    adapter = SAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "SA300000000000003"
        )


@pytest.mark.asyncio
async def test_vat_normalizer_rejects_bad_prefix():
    adapter = SAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "400000000000003"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_real_matches():
    adapter = SAAdapter()
    matches = await adapter.search_by_name("Saudi Telecom", limit=5)
    assert any(m.identifiers[-1].value == "1010150269" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "cr",
    [
        "1010150269",  # STC
        "1010010813",  # SABIC
        "2052101150",  # Saudi Aramco (GLEIF registeredAs)
        "4030001588",  # Saudi National Bank (GLEIF registeredAs)
    ],
)
async def test_lookup_real_cr_numbers(cr: str):
    adapter = SAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, cr
    )
    assert details is not None
    assert details.country == "SA"
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == cr
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_stc_returns_real_filings():
    adapter = SAAdapter()
    filings = await adapter.fetch_financials("1010150269", years=3)
    assert filings, "expected at least one filing for STC"
    latest = filings[0]
    assert latest.currency == "SAR"
    assert latest.structured_data["tadawul_symbol"] == "7010"
    assert latest.structured_data["statements"]["Balance Sheet"]["Total Assets"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_reports_live_capabilities():
    adapter = SAAdapter()
    health = await adapter.health_check()
    assert health.country_code == "SA"
    assert health.status in {AdapterStatus.OK, AdapterStatus.ERROR}
    assert health.capabilities["financials"] is True
