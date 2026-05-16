from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.pl import PLAdapter
from packages.adapters.pl.adapter import (
    _normalize_krs,
    _normalize_nip,
    _normalize_regon,
)
from packages.shared.models import IdentifierType


def test_normalize_krs_pads_short_numbers():
    assert _normalize_krs("28860") == "0000028860"
    assert _normalize_krs(" 0000028860 ") == "0000028860"


def test_normalize_krs_rejects_non_digits():
    with pytest.raises(InvalidIdentifierError):
        _normalize_krs("ABCDEFGHIJ")


def test_normalize_nip_strips_prefix_and_validates_checksum():
    assert _normalize_nip("PL 774-000-14-54") == "7740001454"


def test_normalize_nip_rejects_bad_checksum():
    with pytest.raises(InvalidIdentifierError):
        _normalize_nip("7740001455")


def test_normalize_regon_accepts_9_and_14_digit():
    assert _normalize_regon("610188201") == "610188201"
    assert _normalize_regon("61018820100000") == "61018820100000"


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = PLAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("orlen")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_orlen_by_krs():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.KRS, "0000028860")
    assert details is not None
    assert "ORLEN" in details.name.upper()
    assert details.country == "PL"
    nip_ids = [i for i in details.identifiers if i.type == IdentifierType.NIP]
    assert nip_ids and nip_ids[0].value == "7740001454"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_cd_projekt_pulls_capital_and_nace():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.KRS, "0000006865")
    assert details is not None
    assert "CD PROJEKT" in details.name.upper()
    assert details.capital_currency == "PLN"
    assert details.capital_amount is not None and details.capital_amount > 0
    assert any(code.startswith("62") for code in details.nace_codes)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_nip_resolves_via_biala_lista():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.NIP, "7740001454")
    assert details is not None
    assert details.id == "0000028860"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_with_pl_prefix():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "PL6920000013")
    assert details is not None
    assert "KGHM" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = PLAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PL"
    assert health.status.value in {"ok", "degraded"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_empty_for_blocked_rdf():
    adapter = PLAdapter()
    filings = await adapter.fetch_financials("0000028860")
    assert filings == []
