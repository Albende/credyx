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
async def test_vat_normalizer_strips_sa_prefix():
    adapter = SAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "SA300000000000003"
    )
    assert details is not None
    assert details.identifiers[0].value == "300000000000003"


@pytest.mark.asyncio
async def test_vat_normalizer_rejects_bad_prefix():
    adapter = SAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "400000000000003"
        )


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = SAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Aramco")


@pytest.mark.asyncio
async def test_lookup_aramco_cr_returns_link():
    adapter = SAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "2052101140"
    )
    assert details is not None
    assert details.id == "2052101140"
    assert details.source_url is not None
    assert "2052101140" in details.source_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cr",
    [
        "2052101140",  # Saudi Aramco
        "1010150269",  # STC
        "1010008668",  # Saudi National Bank
        "1010010813",  # SABIC
    ],
)
async def test_lookup_real_cr_numbers_normalize(cr: str):
    adapter = SAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, cr
    )
    assert details is not None
    assert details.id == cr
    assert details.country == "SA"


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = SAAdapter()
    filings = await adapter.fetch_financials("2052101140")
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_probes_real_hosts():
    adapter = SAAdapter()
    health = await adapter.health_check()
    assert health.country_code == "SA"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
