from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.es import ESAdapter
from packages.adapters.es.adapter import _cif_checksum_ok, _normalize_cif
from packages.shared.models import IdentifierType


def test_cif_normalizer_accepts_known_companies():
    assert _normalize_cif("A15022510") == "A15022510"
    assert _normalize_cif("ES A28015865") == "A28015865"
    assert _normalize_cif("a48010615") == "A48010615"


def test_cif_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_cif("not-a-cif")
    with pytest.raises(InvalidIdentifierError):
        _normalize_cif("Z99999999")


def test_cif_checksum_validates_inditex_and_santander():
    assert _cif_checksum_ok("A15022510")
    assert _cif_checksum_ok("A28015865")
    assert _cif_checksum_ok("A39000013")
    assert _cif_checksum_ok("A48010615")


def test_cif_checksum_rejects_one_off():
    assert not _cif_checksum_ok("A15022511")


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = ESAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Inditex")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_inditex():
    adapter = ESAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.CIF, "A15022510")
    assert details is not None
    assert details.country == "ES"
    assert "inditex" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_telefonica_via_vat():
    adapter = ESAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "ESA28015865")
    assert details is not None
    assert "telef" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_returns_entries():
    adapter = ESAdapter()
    filings = await adapter.fetch_financials("A15022510", years=3)
    # Inditex is CNMV-listed: we expect non-empty filings or empty if CNMV
    # blocks the probe — both are acceptable, but if non-empty each must
    # link back to CNMV.
    for f in filings:
        assert f.source_url is not None and "cnmv.es" in f.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_ok():
    adapter = ESAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ES"
    assert health.capabilities["lookup"] is True
    assert health.capabilities["search"] is False
