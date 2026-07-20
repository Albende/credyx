"""Integration tests for the Philippines adapter (PSE Edge).

The integration tests hit the real PSE Edge disclosure portal — no fixtures,
no mocks. PSE Edge markup is stable but the disclosure set grows over time,
so network-side tests guard structural invariants rather than exact strings.
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ph import PHAdapter
from packages.adapters.ph.adapter import (
    _fiscal_year,
    _normalize_symbol,
    _parse_ph_date,
)
from packages.shared.models import FilingType, IdentifierType


SM = "SM"
AYALA = "AC"
BDO = "BDO"
JFC = "JFC"


def test_normalize_symbol_strips_and_uppercases():
    assert _normalize_symbol("sm") == "SM"
    assert _normalize_symbol("  JFC ") == "JFC"
    assert _normalize_symbol("PSE:AC") == "AC"
    with pytest.raises(InvalidIdentifierError):
        _normalize_symbol("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_symbol("!!!not-valid!!!")


def test_fiscal_year_from_label_and_announce():
    assert _fiscal_year("01 SM - SEC 17-A as of 31 December 2025", "") == 2025
    assert _fiscal_year("2024 Ayala Corporation_SEC Form 17-A", "") == 2024
    assert _fiscal_year("", "Apr 16, 2026 11:50 AM") == 2025
    assert _fiscal_year("", "") is None


def test_parse_ph_date_handles_common_formats():
    assert _parse_ph_date("1976-01-23") == date(1976, 1, 23)
    assert _parse_ph_date("01/23/1976") == date(1976, 1, 23)
    assert _parse_ph_date("January 23, 1976") == date(1976, 1, 23)
    assert _parse_ph_date("May 15, 1960") == date(1960, 5, 15)
    assert _parse_ph_date(None) is None
    assert _parse_ph_date("not a date") is None


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = PHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, SM)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_sm():
    adapter = PHAdapter()
    matches = await adapter.search_by_name("SM Investments", limit=10)
    assert isinstance(matches, list)
    assert matches
    assert any(m.country == "PH" for m in matches)
    assert all(m.id and m.name for m in matches)
    assert any(m.id == SM for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_sm_by_symbol():
    adapter = PHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, SM
    )
    assert details is not None
    assert details.id == SM
    assert details.country == "PH"
    assert details.name
    assert details.incorporation_date is not None
    assert details.registered_address
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == SM
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    adapter = PHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "ZZZZZ"
    )
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_for_listed_companies():
    adapter = PHAdapter()
    for symbol in (SM, AYALA, JFC):
        filings = await adapter.fetch_financials(symbol, years=3)
        assert isinstance(filings, list)
        assert filings
        years = [f.year for f in filings]
        assert len(years) == len(set(years))
        for f in filings:
            assert f.company_id == symbol
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "PHP"
            assert f.period_end == date(f.year, 12, 31)
            assert f.document_url and f.document_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_status():
    adapter = PHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PH"
    assert health.status.value in ("ok", "error")
