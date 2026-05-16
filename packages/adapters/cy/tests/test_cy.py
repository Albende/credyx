from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.cy import CYAdapter
from packages.adapters.cy.adapter import _normalize_he, _normalize_vat
from packages.shared.models import IdentifierType


def test_normalize_he_strips_prefix_and_pads():
    assert _normalize_he("HE 165") == "000000165"
    assert _normalize_he("he6059") == "000006059"
    assert _normalize_he("192919") == "000192919"


def test_normalize_he_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_he("HE-ABC")
    with pytest.raises(InvalidIdentifierError):
        _normalize_he("")


def test_normalize_vat_strips_prefix_and_validates_letter():
    assert _normalize_vat("CY 12345678X") == "12345678X"
    assert _normalize_vat("cy-99999999z") == "99999999Z"


def test_normalize_vat_rejects_bad_shape():
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("CY1234567")  # missing letter
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("CY12345678")  # missing letter
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("CY1234567XY")  # too many trailing letters


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_bank_of_cyprus():
    adapter = CYAdapter()
    matches = await adapter.search_by_name("BANK OF CYPRUS", limit=10)
    assert matches, "Expected at least one DRCOR match for 'BANK OF CYPRUS'"
    assert any("bank of cyprus" in m.name.lower() for m in matches)
    assert any(m.country == "CY" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bank_of_cyprus_by_he():
    adapter = CYAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "HE165"
    )
    assert details is not None
    assert "bank of cyprus" in details.name.lower()
    assert details.country == "CY"
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and "165" in i.value
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_he_returns_none():
    adapter = CYAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "HE999999999"
    )
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_empty():
    adapter = CYAdapter()
    filings = await adapter.fetch_financials("HE165", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = CYAdapter()
    health = await adapter.health_check()
    assert health.country_code == "CY"
    assert health.status.value in {"ok", "error"}
