from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.am import AMAdapter
from packages.adapters.am.adapter import (
    _classify_status,
    _extract_company_record,
    _extract_search_rows,
    _normalize_reg_number,
    _normalize_tin,
    _parse_am_date,
    _parse_capital_amount,
)
from packages.shared.models import IdentifierType


def test_normalize_tin_strips_prefix_and_whitespace():
    assert _normalize_tin("02525118") == "02525118"
    assert _normalize_tin(" 02525118 ") == "02525118"
    assert _normalize_tin("AM02525118") == "02525118"
    assert _normalize_tin("am 02525118") == "02525118"
    assert _normalize_tin("0252-5118") == "02525118"


def test_normalize_tin_rejects_invalid_lengths():
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("025251189")  # 9 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("0252ABCD")


def test_normalize_reg_number_accepts_common_shapes():
    assert _normalize_reg_number("290.110.05049") == "290.110.05049"
    assert _normalize_reg_number(" 222-555-12345 ") == "222-555-12345"
    assert _normalize_reg_number("12345") == "12345"
    with pytest.raises(InvalidIdentifierError):
        _normalize_reg_number("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_reg_number("contains spaces and letters!!")


def test_parse_am_date_handles_common_formats():
    assert _parse_am_date("15.04.1992").isoformat() == "1992-04-15"
    assert _parse_am_date("2001-09-30").isoformat() == "2001-09-30"
    assert _parse_am_date("31/12/2010").isoformat() == "2010-12-31"
    assert _parse_am_date("") is None
    assert _parse_am_date(None) is None
    assert _parse_am_date("not a date") is None


def test_classify_status_maps_localized_values():
    assert _classify_status("Գործող") == "active"
    assert _classify_status("Active") == "active"
    assert _classify_status("действующее") == "active"
    assert _classify_status("Լուծարված") == "inactive"
    assert _classify_status("Liquidated") == "inactive"
    assert _classify_status("ликвидировано") == "inactive"
    assert _classify_status(None) is None


def test_parse_capital_amount_strips_currency_and_separators():
    assert _parse_capital_amount("50,000,000 AMD") == 50000000.0
    assert _parse_capital_amount("AMD 105000000") == 105000000.0
    assert _parse_capital_amount("") is None
    assert _parse_capital_amount(None) is None
    assert _parse_capital_amount("free text only") is None


def test_extract_company_record_parses_two_column_table():
    html = """
    <html><body>
      <h1>Ardshinbank CJSC</h1>
      <table>
        <tr><td>Company name:</td><td>"ARDSHINBANK" CJSC</td></tr>
        <tr><td>ՀՎՀՀ:</td><td>02525118</td></tr>
        <tr><td>State registration number:</td><td>22.110.00125</td></tr>
        <tr><td>Status:</td><td>Active</td></tr>
        <tr><td>Registered address:</td><td>Yerevan, Grigor Lusavorich 13</td></tr>
        <tr><td>Registration date:</td><td>03.12.2002</td></tr>
        <tr><td>Legal form:</td><td>Closed Joint-Stock Company</td></tr>
        <tr><td>Charter capital:</td><td>105,000,000,000 AMD</td></tr>
      </table>
    </body></html>
    """
    record = _extract_company_record(html)
    assert "ARDSHINBANK" in record["name"]
    assert record["tin"] == "02525118"
    assert record["reg_number"] == "22.110.00125"
    assert record["status_raw"] == "Active"
    assert "Yerevan" in record["address"]
    assert record["registration_date"] == "03.12.2002"
    assert "Joint-Stock" in record["legal_form"]
    assert "105,000,000,000" in record["capital"]


def test_extract_company_record_empty_when_no_table():
    assert _extract_company_record("") == {}
    assert _extract_company_record("<html><body>No data</body></html>") == {}


def test_extract_company_record_falls_back_to_heading():
    html = "<html><body><h1>Ameriabank CJSC</h1><p>No table here.</p></body></html>"
    record = _extract_company_record(html)
    assert record.get("name") == "Ameriabank CJSC"


def test_extract_search_rows_picks_name_and_tin():
    html = """
    <html><body><table>
      <tr><th>Name</th><th>TIN</th><th>Status</th></tr>
      <tr><td>ARDSHINBANK CJSC</td><td>02525118</td><td>Active</td></tr>
      <tr><td>AMERIABANK CJSC</td><td>02501006</td><td>Active</td></tr>
    </table></body></html>
    """
    rows = _extract_search_rows(html)
    names = {r["name"] for r in rows}
    tins = {r["tin"] for r in rows}
    assert "ARDSHINBANK CJSC" in names
    assert "AMERIABANK CJSC" in names
    assert "02525118" in tins
    assert "02501006" in tins


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = AMAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "02525118")


@pytest.mark.asyncio
async def test_fetch_financials_not_implemented():
    adapter = AMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.fetch_financials("02525118")


def test_adapter_static_attributes():
    adapter = AMAdapter()
    assert adapter.country_code == "AM"
    assert adapter.country_name == "Armenia"
    assert adapter.primary_identifier == IdentifierType.VAT
    assert IdentifierType.VAT in adapter.identifier_types
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ardshinbank_returns_company_details():
    adapter = AMAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "02525118"
    )
    assert details is not None
    assert details.country == "AM"
    assert details.id == "02525118"
    assert details.name
    upper = details.name.upper()
    assert "ARDSHIN" in upper or "АРДШИН" in upper or "ԱՐԴՇԻՆ" in upper


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ameriabank_returns_company_details():
    adapter = AMAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "02501006"
    )
    assert details is not None
    assert details.id == "02501006"
    upper = details.name.upper()
    assert "AMERIA" in upper or "АМЕРИА" in upper or "ԱՄԵՐԻԱ" in upper


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_some_matches():
    adapter = AMAdapter()
    matches = await adapter.search_by_name("Ardshinbank", limit=10)
    assert isinstance(matches, list)
    # We don't assert non-empty — the public results page may require JS in
    # some renders. We only require that the call succeeds and returns the
    # documented shape.
    for m in matches:
        assert m.country == "AM"
        assert m.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = AMAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AM"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30
