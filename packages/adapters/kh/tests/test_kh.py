"""Integration tests for the Cambodia adapter (MoC + CSX).

Integration tests hit businessregistration.moc.gov.kh and csx.com.kh —
no fixtures, no mocks. Network failures or upstream schema changes
should ``pytest.skip`` rather than fail the suite.
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.kh import KHAdapter
from packages.adapters.kh.adapter import (
    _detect_csx_ticker,
    _normalize_moc_number,
    _normalize_vat_tin,
    _parse_kh_date,
)
from packages.shared.models import FilingType, IdentifierType


ACLEDA_NAME = "ACLEDA Bank Plc."
PPSP_NAME = "Phnom Penh Special Economic Zone Plc"
PWSA_NAME = "Phnom Penh Water Supply Authority"
PAS_NAME = "Sihanoukville Autonomous Port"


def test_normalize_moc_number_zero_pads_and_validates():
    assert _normalize_moc_number("12345") == "00012345"
    assert _normalize_moc_number(" 00012345 ") == "00012345"
    assert _normalize_moc_number("0001-2345") == "00012345"
    assert _normalize_moc_number("KH00012345") == "00012345"
    assert _normalize_moc_number("1234567890") == "1234567890"
    with pytest.raises(InvalidIdentifierError):
        _normalize_moc_number("ABCDEFGH")
    with pytest.raises(InvalidIdentifierError):
        _normalize_moc_number("")


def test_normalize_vat_tin_validates():
    assert _normalize_vat_tin("1001234567") == "1001234567"
    assert _normalize_vat_tin("100-123-456") == "100123456"
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat_tin("12")
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat_tin("ABCDEFGHIJ")


def test_parse_kh_date_handles_iso_and_dmy():
    assert _parse_kh_date("2010-04-19") == date(2010, 4, 19)
    assert _parse_kh_date("19/04/2010") == date(2010, 4, 19)
    assert _parse_kh_date("19-04-2010") == date(2010, 4, 19)
    assert _parse_kh_date(None) is None
    assert _parse_kh_date("not a date") is None


def test_detect_csx_ticker_known_issuers():
    assert _detect_csx_ticker(ACLEDA_NAME) == ("ABC", "KHR")
    assert _detect_csx_ticker(PPSP_NAME) == ("PPSP", "KHR")
    assert _detect_csx_ticker(PWSA_NAME) == ("PWSA", "KHR")
    assert _detect_csx_ticker(PAS_NAME) == ("PAS", "KHR")
    assert _detect_csx_ticker("Some Random Co Ltd") == (None, None)


def test_detect_csx_ticker_trusts_explicit_field():
    assert _detect_csx_ticker("", {"csx_symbol": "ABC"}) == ("ABC", "KHR")
    # Non-ticker shapes are rejected so we never fabricate a URL.
    assert _detect_csx_ticker("", {"csx_symbol": "lowercase"}) == (None, None)
    assert _detect_csx_ticker("", {"csx_symbol": "TOOLONGSYMBOL"}) == (None, None)


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = KHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "00012345")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_acleda_returns_list():
    adapter = KHAdapter()
    matches = await adapter.search_by_name("ACLEDA", limit=10)
    assert isinstance(matches, list)
    for m in matches:
        assert m.country == "KH"
        assert m.id and m.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_empty_returns_empty():
    adapter = KHAdapter()
    matches = await adapter.search_by_name("   ", limit=5)
    assert matches == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    adapter = KHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "00000001"
    )
    assert details is None or details.id == "00000001"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_csx_listed_issuers():
    adapter = KHAdapter()
    # The MoC payload may not carry the CSX ticker; the adapter falls back
    # to the known-issuer name table once ``_moc_lookup`` returns. Either
    # way, every emitted filing must point at a verified CSX URL.
    for moc_id in ("00012345", "00067890", "00011111", "00022222"):
        filings = await adapter.fetch_financials(moc_id, years=3)
        assert isinstance(filings, list)
        for f in filings:
            assert f.company_id == moc_id.zfill(8)
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "KHR"
            assert f.document_url and f.document_url.startswith("https://csx.com.kh/")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_status():
    adapter = KHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "KH"
    assert health.status.value in ("ok", "error")
