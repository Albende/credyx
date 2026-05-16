from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.it import ITAdapter
from packages.adapters.it.adapter import _normalize_piva, _piva_checksum_ok
from packages.shared.models import AdapterStatus, IdentifierType


def test_piva_checksum_known_good():
    # Eni, Enel, Intesa Sanpaolo, UniCredit — all real Partite IVA.
    for piva in (
        "00484960588",
        "00811720580",
        "00799960158",
        "00348170101",
    ):
        assert _piva_checksum_ok(piva), piva


def test_piva_checksum_rejects_tweaked_check_digit():
    assert not _piva_checksum_ok("00484960589")


def test_normalize_piva_strips_country_prefix_and_separators():
    assert _normalize_piva("IT00484960588") == "00484960588"
    assert _normalize_piva(" 00 484 960 588 ") == "00484960588"
    assert _normalize_piva("00484960588") == "00484960588"


def test_normalize_piva_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_piva("12345")


def test_normalize_piva_rejects_bad_checksum():
    with pytest.raises(InvalidIdentifierError):
        _normalize_piva("00484960589")


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = ITAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Eni")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = ITAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.SIREN, "00484960588")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = ITAdapter()
    health = await adapter.health_check()
    assert health.country_code == "IT"
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_eni_via_vies():
    adapter = ITAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "IT00484960588"
    )
    assert details is not None
    assert details.country == "IT"
    assert details.id == "00484960588"
    assert "eni" in details.name.lower()
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_enel_via_vies():
    adapter = ITAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "00811720580"
    )
    assert details is not None
    assert "enel" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_returns_borsa_links():
    adapter = ITAdapter()
    filings = await adapter.fetch_financials("00484960588", years=3)
    assert len(filings) == 3
    for f in filings:
        assert f.currency == "EUR"
        assert f.document_url is not None
        assert "borsaitaliana.it" in f.document_url


@pytest.mark.asyncio
async def test_fetch_financials_unlisted_returns_empty():
    adapter = ITAdapter()
    # All-zeros passes the mod-10 check and is not in the Borsa Italiana
    # listed-issuer map — exercises the unlisted branch without hitting VIES.
    candidate = "00000000000"
    assert _piva_checksum_ok(candidate)
    filings = await adapter.fetch_financials(candidate, years=5)
    assert filings == []
