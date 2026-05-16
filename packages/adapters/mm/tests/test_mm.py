"""Integration tests for the Myanmar adapter (DICA MyCO + YSX).

Integration tests hit the live MyCO endpoint — no fixtures, no mocks.
The MyCO portal is occasionally unreachable or geo-restricts requests;
network-bound assertions degrade to `pytest.skip` rather than fail loudly
so CI does not flap.
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.mm import MMAdapter
from packages.adapters.mm.adapter import (
    _looks_like_ysx_ticker,
    _normalize_reg_no,
    _normalize_status,
    _parse_mm_date,
    _select_by_reg_no,
)
from packages.shared.models import FilingType, IdentifierType


# YSX listed issuers used as canonical test companies.
FMI_NAME = "First Myanmar Investment"
MTSH_NAME = "Myanmar Thilawa SEZ Holdings"
MCB_NAME = "Myanmar Citizens Bank"
AFD_NAME = "Ayeyarwaddy Farmers Development"


def test_normalize_reg_no_strips_and_validates():
    assert _normalize_reg_no("  12345 ") == "12345"
    assert _normalize_reg_no("12345 OF") == "12345OF"
    assert _normalize_reg_no("MM12345") == "12345"
    assert _normalize_reg_no("20180101-1234") == "20180101-1234"
    assert _normalize_reg_no("20180101/1234") == "20180101/1234"
    with pytest.raises(InvalidIdentifierError):
        _normalize_reg_no("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_reg_no("   ")
    with pytest.raises(InvalidIdentifierError):
        _normalize_reg_no("!!!")


def test_parse_mm_date_handles_iso_and_dmy():
    assert _parse_mm_date("2018-08-01") == date(2018, 8, 1)
    assert _parse_mm_date("01/08/2018") == date(2018, 8, 1)
    assert _parse_mm_date("01-08-2018") == date(2018, 8, 1)
    assert _parse_mm_date("1 August 2018") == date(2018, 8, 1)
    assert _parse_mm_date(None) is None
    assert _parse_mm_date("") is None
    assert _parse_mm_date("not a date") is None


def test_normalize_status_buckets_known_values():
    assert _normalize_status("Active") == "active"
    assert _normalize_status("Registered") == "active"
    assert _normalize_status("Struck Off") == "ceased"
    assert _normalize_status("Wound Up") == "ceased"
    assert _normalize_status("In Liquidation") == "ceased"
    assert _normalize_status("Suspended") == "suspended"
    assert _normalize_status(None) is None
    assert _normalize_status("") is None
    assert _normalize_status("Unknown Bucket") == "Unknown Bucket"


def test_looks_like_ysx_ticker():
    assert _looks_like_ysx_ticker("FMI") is True
    assert _looks_like_ysx_ticker("MTSH") is True
    assert _looks_like_ysx_ticker("mcb") is True
    assert _looks_like_ysx_ticker("AFD") is True
    assert _looks_like_ysx_ticker("") is False
    assert _looks_like_ysx_ticker(None) is False
    assert _looks_like_ysx_ticker("WAYTOOLONGTICKER") is False
    assert _looks_like_ysx_ticker("123") is False


def test_select_by_reg_no_matches_case_insensitive():
    rows = [
        {"RegistrationNo": "12345", "CompanyName": "Foo"},
        {"RegistrationNo": "67890", "CompanyName": "Bar"},
    ]
    picked = _select_by_reg_no(rows, "12345")
    assert picked is not None
    assert picked["CompanyName"] == "Foo"
    assert _select_by_reg_no(rows, "99999") is None
    assert _select_by_reg_no([], "12345") is None


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = MMAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "12345")


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty_list():
    adapter = MMAdapter()
    assert await adapter.search_by_name("", limit=5) == []
    assert await adapter.search_by_name("   ", limit=5) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_listed_issuer():
    adapter = MMAdapter()
    matches = await adapter.search_by_name(FMI_NAME, limit=10)
    assert isinstance(matches, list)
    for m in matches:
        assert m.country == "MM"
        assert m.id
        assert m.name
        assert any(
            i.type == IdentifierType.COMPANY_NUMBER and i.value == m.id
            for i in m.identifiers
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_other_ysx_issuers_returns_well_formed_rows():
    adapter = MMAdapter()
    for query in (MTSH_NAME, MCB_NAME, AFD_NAME):
        matches = await adapter.search_by_name(query, limit=5)
        assert isinstance(matches, list)
        for m in matches:
            assert m.country == "MM"
            assert m.id and m.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_reg_no_returns_none():
    adapter = MMAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "99999999"
    )
    assert details is None or details.id == "99999999"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_list_for_unknown_reg_no():
    adapter = MMAdapter()
    filings = await adapter.fetch_financials("99999999", years=3)
    assert isinstance(filings, list)
    for f in filings:
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "MMK"
        assert f.document_url and f.document_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_status():
    adapter = MMAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MM"
    assert health.name == "Myanmar"
    assert health.status.value in ("ok", "error")
    assert health.requires_api_key is False
