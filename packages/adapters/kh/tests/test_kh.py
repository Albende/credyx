"""Integration tests for the Cambodia adapter (GLEIF + CSX).

Integration tests hit api.gleif.org and csx.com.kh — no fixtures, no
mocks. Network failures or upstream schema changes should ``pytest.skip``
rather than fail the suite.
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.kh import KHAdapter
from packages.adapters.kh.adapter import (
    _english_name,
    _normalize_moc_number,
    _normalize_vat_tin,
    _parse_kh_date,
    _report_year,
    _view_attach_url,
)
from packages.shared.models import FilingType, IdentifierType


ACLEDA_MOC = "00003077"


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


def test_english_name_prefers_alternative_language_legal_name():
    entity = {
        "legalName": {"name": "ធនាគារ អេស៊ីលីដា", "language": "km"},
        "otherNames": [
            {
                "name": "ACLEDA Bank Plc.",
                "language": "en",
                "type": "ALTERNATIVE_LANGUAGE_LEGAL_NAME",
            }
        ],
    }
    assert _english_name(entity) == "ACLEDA Bank Plc."


def test_report_year_from_title_then_publish_date():
    assert _report_year({"title": "The Annual report of ACLEDA in 2024"}) == 2024
    assert _report_year({"title": "Annual report", "date": "01/04/2024"}) == 2023
    assert _report_year({"title": "Annual report"}) is None


def test_view_attach_url_builds_get_endpoint():
    url = _view_attach_url(
        "https://csx.com.kh",
        "/api/v1/website",
        [
            {
                "fileName": "abc.pdf",
                "boardId": "annualreportabc",
                "fileOrder": 0,
                "postId": 32,
                "boardLang": "en",
                "originalFileName": "orig.pdf",
            }
        ],
    )
    assert url is not None
    assert url.startswith(
        "https://csx.com.kh/api/v1/website/file/view-attach?"
    )
    assert "postId=32" in url and "fileName=abc.pdf" in url
    assert _view_attach_url("https://csx.com.kh", "/api/v1/website", []) is None


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = KHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.SIREN, "00012345")


@pytest.mark.asyncio
async def test_search_empty_returns_empty():
    adapter = KHAdapter()
    matches = await adapter.search_by_name("   ", limit=5)
    assert matches == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_acleda_returns_registry_record():
    adapter = KHAdapter()
    matches = await adapter.search_by_name("ACLEDA", limit=10)
    assert isinstance(matches, list)
    assert matches, "expected at least one GLEIF match for ACLEDA"
    for m in matches:
        assert m.country == "KH"
        assert m.id and m.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_acleda_by_moc_number():
    adapter = KHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, ACLEDA_MOC
    )
    assert details is not None
    assert details.country == "KH"
    assert details.id == ACLEDA_MOC
    assert "ACLEDA" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    adapter = KHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "99999999"
    )
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_acleda_returns_real_pdfs():
    adapter = KHAdapter()
    filings = await adapter.fetch_financials(ACLEDA_MOC, years=3)
    assert filings, "expected CSX annual-report filings for ACLEDA"
    for f in filings:
        assert f.company_id == ACLEDA_MOC
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "KHR"
        assert f.document_format == "pdf"
        assert f.document_url and "csx.com.kh" in f.document_url
        assert "view-attach" in f.document_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_unlisted_returns_empty():
    adapter = KHAdapter()
    # First Finance Plc (MoC 00016858) is in GLEIF but is not CSX-listed.
    filings = await adapter.fetch_financials("00016858", years=3)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_status():
    adapter = KHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "KH"
    assert health.status.value in ("ok", "error")
