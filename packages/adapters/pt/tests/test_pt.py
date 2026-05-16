from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.pt import PTAdapter
from packages.adapters.pt.adapter import _nipc_checksum_ok, _normalize_nipc
from packages.shared.models import IdentifierType


def test_nipc_normalizer_accepts_known_companies():
    assert _normalize_nipc("500697256") == "500697256"
    assert _normalize_nipc("PT 504499777") == "504499777"
    assert _normalize_nipc("pt-500100144") == "500100144"


def test_nipc_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipc("not-a-nipc")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipc("12345")
    with pytest.raises(InvalidIdentifierError):
        # Right shape, wrong checksum.
        _normalize_nipc("500697250")


def test_nipc_checksum_validates_known_issuers():
    assert _nipc_checksum_ok("500697256")  # EDP
    assert _nipc_checksum_ok("504499777")  # Galp
    assert _nipc_checksum_ok("500100144")  # Jerónimo Martins
    assert _nipc_checksum_ok("501525882")  # Millennium BCP


def test_nipc_checksum_rejects_one_off():
    assert not _nipc_checksum_ok("500697255")
    assert not _nipc_checksum_ok("504499770")


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = PTAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Galp")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = PTAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.SIREN, "500697256")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_edp():
    adapter = PTAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "500697256"
    )
    assert details is not None
    assert details.country == "PT"
    assert "edp" in details.name.lower() or "energias" in details.name.lower()
    assert any(i.value == "PT500697256" for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_galp_via_vat():
    adapter = PTAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "PT504499777")
    assert details is not None
    assert "galp" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_returns_pointers():
    adapter = PTAdapter()
    filings = await adapter.fetch_financials("500697256", years=3)
    # EDP is CMVM-listed: filings should be non-empty unless CMVM blocks
    # our probe. Either case is acceptable, but non-empty entries must
    # link back to CMVM.
    for f in filings:
        assert f.source_url is not None and "cmvm.pt" in f.source_url
        assert f.currency == "EUR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_ok():
    adapter = PTAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PT"
    assert health.capabilities["lookup"] is True
    assert health.capabilities["search"] is False
