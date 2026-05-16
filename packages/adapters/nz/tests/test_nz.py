"""Integration tests for the NZ (NZBN Register) adapter.

These tests hit the real NZBN API. Require env var NZ_NZBN_API_KEY.
Marked `integration` so CI can opt-out with `-m "not integration"`.
"""
from __future__ import annotations

import os

import pytest

from packages.adapters.nz import NZAdapter
from packages.shared.models import FinancialFiling, IdentifierType


_FONTERRA_NZBN = "9429036018110"


def _has_key() -> bool:
    return bool(os.getenv("NZ_NZBN_API_KEY"))


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(not _has_key(), reason="NZ_NZBN_API_KEY not set")
async def test_search_finds_fonterra():
    adapter = NZAdapter()
    matches = await adapter.search_by_name("Fonterra", limit=5)
    assert matches, "expected at least one match for Fonterra"
    assert any("fonterra" in m.name.lower() for m in matches)
    for m in matches:
        assert m.country == "NZ"
        assert any(i.type == IdentifierType.COMPANY_NUMBER for i in m.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(not _has_key(), reason="NZ_NZBN_API_KEY not set")
async def test_lookup_fonterra_nzbn():
    adapter = NZAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, _FONTERRA_NZBN
    )
    assert details is not None
    assert "fonterra" in details.name.lower()
    assert details.country == "NZ"
    assert any(
        i.value == _FONTERRA_NZBN and i.label == "NZBN" for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(not _has_key(), reason="NZ_NZBN_API_KEY not set")
async def test_lookup_air_nz_by_company_number():
    adapter = NZAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "13468"
    )
    assert details is not None
    assert "air new zealand" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(not _has_key(), reason="NZ_NZBN_API_KEY not set")
async def test_financials_fonterra_structure():
    adapter = NZAdapter()
    filings = await adapter.fetch_financials(_FONTERRA_NZBN, years=5)
    assert isinstance(filings, list)
    for f in filings:
        assert isinstance(f, FinancialFiling)
        assert f.company_id == _FONTERRA_NZBN
        assert f.currency == "NZD"
