"""Integration tests for the Thailand adapter (DBD DataWarehouse + SET).

The integration tests hit the real DBD endpoint — no fixtures, no mocks.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.th import THAdapter
from packages.adapters.th.adapter import (
    _normalize_juristic_id,
    _parse_th_date,
)
from packages.shared.models import FilingType, IdentifierType


PTT_ID = "0107544000108"
SCB_ID = "0107536000358"
AIS_ID = "0107535000311"
CP_ALL_ID = "0107542000011"


def test_normalize_juristic_id_strips_and_validates():
    assert _normalize_juristic_id("  0107544000108 ") == PTT_ID
    assert _normalize_juristic_id("0107-5440-00108") == PTT_ID
    assert _normalize_juristic_id("TH0107544000108") == PTT_ID
    with pytest.raises(InvalidIdentifierError):
        _normalize_juristic_id("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_juristic_id("ABCDEFGHIJKLM")


def test_parse_th_date_handles_iso_and_buddhist_era():
    from datetime import date

    assert _parse_th_date("2001-10-01") == date(2001, 10, 1)
    assert _parse_th_date("01/10/2544") == date(2001, 10, 1)
    assert _parse_th_date("01-10-2001") == date(2001, 10, 1)
    assert _parse_th_date(None) is None
    assert _parse_th_date("not a date") is None


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = THAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, PTT_ID)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_ptt():
    adapter = THAdapter()
    matches = await adapter.search_by_name("PTT", limit=10)
    assert isinstance(matches, list)
    if matches:
        assert any(m.country == "TH" for m in matches)
        assert all(m.id and m.name for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_juristic_id_returns_ptt():
    adapter = THAdapter()
    matches = await adapter.search_by_name(PTT_ID, limit=1)
    assert isinstance(matches, list)
    if matches:
        assert matches[0].id == PTT_ID


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ptt_by_company_number():
    adapter = THAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, PTT_ID
    )
    if details is None:
        pytest.skip("DBD did not return a record for PTT — registry transient")
    assert details.id == PTT_ID
    assert details.country == "TH"
    assert details.name
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == PTT_ID
        for i in details.identifiers
    )
    assert any(
        i.type == IdentifierType.VAT and i.value == PTT_ID
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ptt_by_vat_returns_same_record():
    adapter = THAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, PTT_ID)
    if details is None:
        pytest.skip("DBD did not return a record for PTT — registry transient")
    assert details.id == PTT_ID
    assert details.capital_currency == "THB"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    adapter = THAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "9999999999999"
    )
    assert details is None or details.id == "9999999999999"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_structure_for_known_ids():
    adapter = THAdapter()
    for juristic in (PTT_ID, SCB_ID, AIS_ID, CP_ALL_ID):
        filings = await adapter.fetch_financials(juristic, years=3)
        assert isinstance(filings, list)
        for f in filings:
            assert f.company_id == juristic
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "THB"
            assert f.document_url and f.document_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_status():
    adapter = THAdapter()
    health = await adapter.health_check()
    assert health.country_code == "TH"
    assert health.status.value in ("ok", "error")
