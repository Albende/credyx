from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ge import GEAdapter
from packages.adapters.ge.adapter import (
    _classify_status,
    _extract_company_record,
    _extract_search_results,
    _normalize_id,
    _parse_capital,
    _parse_ge_date,
)
from packages.shared.models import IdentifierType


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
    assert _classify_status("Active") == "active"
    assert _classify_status("გაუქმებული") == "inactive"
    assert _classify_status("Liquidated") == "inactive"
    assert _classify_status(None) is None


def test_parse_capital_handles_gel_amounts():
    amount, currency = _parse_capital("100 000,00 GEL")
    assert amount == 100000.0
    assert currency == "GEL"

    amount, currency = _parse_capital("5000 ლარი")
    assert amount == 5000.0
    assert currency == "GEL"

    amount, currency = _parse_capital("1,500.50 USD")
    assert amount == 1500.50
    assert currency == "USD"

    amount, currency = _parse_capital("")
    assert amount is None
    assert currency is None


def test_extract_company_record_parses_two_column_table():
    html = """
    <html><body>
      <table>
        <tr><td>დასახელება:</td><td>სს "საქართველოს ბანკი"</td></tr>
        <tr><td>საიდენტიფიკაციო ნომერი:</td><td>204378869</td></tr>
        <tr><td>სამართლებრივი ფორმა:</td><td>სააქციო საზოგადოება</td></tr>
        <tr><td>სტატუსი:</td><td>მოქმედი</td></tr>
        <tr><td>მისამართი:</td><td>თბილისი, გაგარინის ქ. 29ა</td></tr>
        <tr><td>კაპიტალი:</td><td>100 000,00 GEL</td></tr>
        <tr><td>რეგისტრაციის თარიღი:</td><td>21.10.1994</td></tr>
        <tr><td>ხელმძღვანელი:</td><td>Archil Gachechiladze</td></tr>
      </table>
    </body></html>
    """
    record = _extract_company_record(html)
    assert "საქართველოს ბანკი" in record["name"]
    assert record["legal_form"].startswith("სააქციო")
    assert record["status_raw"] == "მოქმედი"
    assert "თბილისი" in record["address"]
    assert record["capital"] == "100 000,00 GEL"
    assert record["registration_date"] == "21.10.1994"
    assert "Archil Gachechiladze" in record["directors"]


def test_extract_company_record_empty_when_no_table():
    assert _extract_company_record("") == {}
    assert _extract_company_record("<html><body>No data</body></html>") == {}


def test_extract_search_results_finds_anchor_matches():
    html = """
    <table>
      <tr><td><a href="main.php?c=app&m=show_legal_person&legal_code=204378869">
        სს საქართველოს ბანკი
      </a></td><td>თბილისი</td></tr>
      <tr><td><a href="/main.php?c=app&m=show_legal_person&legal_code=204854595">
        სს თიბისი ბანკი
      </a></td></tr>
    </table>
    """
    results = _extract_search_results(html)
    ids = [r["id"] for r in results]
    assert "204378869" in ids
    assert "204854595" in ids


def test_extract_search_results_handles_plain_text_fallback():
    html = """
    <table>
      <tr><td>სს საქართველოს ბანკი</td><td>204378869</td></tr>
    </table>
    """
    results = _extract_search_results(html)
    assert results
    assert results[0]["id"] == "204378869"


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = GEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "204378869")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = GEAdapter()
    assert await adapter.fetch_financials("204378869") == []


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
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "204378869"
    )
    assert details is not None
    assert details.country == "GE"
    assert details.id == "204378869"
    assert details.name
    upper = details.name.upper()
    assert any(
        token in upper for token in ("BANK OF GEORGIA", "BOG", "ბანკი")
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_tbc_bank_returns_company_details():
    adapter = GEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "204854595"
    )
    assert details is not None
    assert details.id == "204854595"
    upper = details.name.upper()
    assert any(token in upper for token in ("TBC", "თიბისი"))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = GEAdapter()
    results = await adapter.search_by_name("Bank of Georgia", limit=5)
    assert isinstance(results, list)
    if results:
        # The NAPR result list should at least include Bank of Georgia
        # (204378869) for this query.
        assert any(r.id == "204378869" for r in results)
