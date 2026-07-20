from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ge import GEAdapter
from packages.adapters.ge.adapter import (
    _classify_status,
    _normalize_id,
    _parse_ge_date,
    _parse_search_rows,
    _reportal_directors,
)
from packages.shared.models import FilingType, IdentifierType


def test_normalize_id_accepts_clean_nine_digits():
    assert _normalize_id("204378869") == "204378869"
    assert _normalize_id(" 204378869 ") == "204378869"
    assert _normalize_id("204-378-869") == "204378869"
    assert _normalize_id("GE204378869") == "204378869"
    assert _normalize_id("ge 204378869") == "204378869"


def test_normalize_id_rejects_wrong_length_or_chars():
    with pytest.raises(InvalidIdentifierError):
        _normalize_id("1234")
    with pytest.raises(InvalidIdentifierError):
        _normalize_id("2043788690")  # 10 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_id("20437886A")


def test_parse_ge_date_handles_common_formats():
    assert _parse_ge_date("15.04.1995").isoformat() == "1995-04-15"
    assert _parse_ge_date("1995-04-15").isoformat() == "1995-04-15"
    assert _parse_ge_date("15/04/1995").isoformat() == "1995-04-15"
    assert _parse_ge_date("") is None
    assert _parse_ge_date(None) is None
    assert _parse_ge_date("not a date") is None


def test_classify_status_handles_georgian_and_english():
    assert _classify_status("მოქმედი") == "active"
    assert _classify_status("აქტიური") == "active"
    assert _classify_status("Active") == "active"
    assert _classify_status("გაუქმებული") == "inactive"
    assert _classify_status("Liquidated") == "inactive"
    assert _classify_status(None) is None


def test_parse_search_rows_extracts_legal_person():
    html = """
    <table class="main_tbl">
      <tbody>
        <tr>
          <td><a href="javascript:void(0)" onclick="show_legal_person(244586)">
            <img src="info.png"></a></td>
          <td><span style="font-weight:bold">204378869</span></td>
          <td><span style="font-weight:bold"></span></td>
          <td> სს საქართველოს ბანკი </td>
          <td> სააქციო საზოგადოება </td>
          <td><span class="st1"> აქტიური </span></td>
        </tr>
      </tbody>
    </table>
    """
    rows = _parse_search_rows(html)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "204378869"
    assert row["record_id"] == "244586"
    assert "საქართველოს ბანკი" in row["name"]
    assert row["legal_form"].startswith("სააქციო")
    assert "აქტიური" in row["status_raw"]


def test_parse_search_rows_skips_rows_without_id_code():
    html = """
    <table>
      <tr><td>no record link here</td><td>404788529</td></tr>
    </table>
    """
    assert _parse_search_rows(html) == []
    assert _parse_search_rows("") == []


def test_reportal_directors_builds_from_json():
    payload = {
        "directors": [
            {"FirstName": "დავით", "LastName": "მამულაიშვილი", "PersonType": "დირექტორი"},
            {"FirstName": "დავით", "LastName": "მამულაიშვილი", "PersonType": "დირექტორი"},
            {"FirstName": "ანა", "LastName": "კოსტავა", "PersonType": None},
        ]
    }
    directors = _reportal_directors(payload)
    assert [d.name for d in directors] == ["დავით მამულაიშვილი", "ანა კოსტავა"]
    assert directors[0].role == "დირექტორი"
    assert _reportal_directors({}) == []


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = GEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "204378869")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = GEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "GE"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bank_of_georgia_returns_company_details():
    adapter = GEAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "204378869")
    assert details is not None
    assert details.country == "GE"
    assert details.id == "204378869"
    assert "ბანკი" in details.name
    assert details.status == "active"
    assert details.incorporation_date is not None
    assert details.directors


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_tbc_bank_returns_company_details():
    adapter = GEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "204854595"
    )
    assert details is not None
    assert details.id == "204854595"
    assert "თიბისი" in details.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = GEAdapter()
    results = await adapter.search_by_name("სილქნეტი", limit=5)
    assert results
    assert any(r.id == "204566978" for r in results)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_filing_metadata():
    adapter = GEAdapter()
    filings = await adapter.fetch_financials("204566978", years=3)
    assert filings
    latest = filings[0]
    assert latest.company_id == "204566978"
    assert latest.type == FilingType.ANNUAL_REPORT
    assert latest.currency == "GEL"
    assert latest.document_url is None
    assert latest.source_url and "reportal.ge" in latest.source_url
