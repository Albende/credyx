"""Unit + integration tests for the PE adapter.

Integration tests hit the BVL/SMV "dataondemand" public API directly
(https://dataondemand.bvl.com.pe) — no key, no mocks. Tests MUST NOT pass
on mocked responses.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.pe import PEAdapter
from packages.adapters.pe.adapter import _fold
from packages.shared.models import IdentifierType


def test_fold_strips_accents_and_uppercases():
    assert _fold("Compañía") == "COMPANIA"
    assert _fold("  buenaventura ") == "BUENAVENTURA"
    assert _fold("Pacasmayo") == "PACASMAYO"


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier_type():
    adapter = PEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "61200")


@pytest.mark.asyncio
async def test_empty_identifier_rejected():
    adapter = PEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "")


@pytest.mark.asyncio
async def test_empty_search_returns_empty():
    adapter = PEAdapter()
    assert await adapter.search_by_name("") == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_by_name_live():
    adapter = PEAdapter()
    matches = await adapter.search_by_name("buenaventura", limit=5)
    assert matches
    assert any("BUENAVENTURA" in _fold(m.name) for m in matches)
    assert all(m.country == "PE" for m in matches)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lookup_by_company_code_live():
    adapter = PEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "61200"
    )
    assert details is not None
    assert "BUENAVENTURA" in _fold(details.name)
    assert any(i.value == "B20003" for i in details.identifiers)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lookup_by_rpj_alias_live():
    adapter = PEAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.OTHER, "CD0005")
    assert details is not None
    assert "PACASMAYO" in _fold(details.name)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_financials_live():
    adapter = PEAdapter()
    filings = await adapter.fetch_financials("61200", years=3)
    assert filings
    latest = filings[0]
    assert latest.currency == "PEN"
    assert latest.structured_data
    assert latest.structured_data["bvl_financial_ratios"]
