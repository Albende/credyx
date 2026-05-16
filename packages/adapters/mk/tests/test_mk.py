from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.mk import MKAdapter
from packages.adapters.mk.adapter import (
    _classify_status,
    _normalize_edb,
    _normalize_embs,
    _parse_capital,
    _parse_filing_years,
    _parse_mk_date,
    _parse_search_results,
)
from packages.shared.models import IdentifierType


def test_normalize_embs_pads_and_validates():
    assert _normalize_embs("4068916") == "4068916"
    assert _normalize_embs(" 4068916 ") == "4068916"
    assert _normalize_embs("40-689-16") == "4068916"
    # Left-padded to 7 digits.
    assert _normalize_embs("12345") == "0012345"


def test_normalize_embs_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        _normalize_embs("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_embs("12345678")  # 8 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_embs("ABC1234")


def test_normalize_edb_strips_prefix_and_validates():
    assert _normalize_edb("4030996115218") == "4030996115218"
    assert _normalize_edb(" 4030996115218 ") == "4030996115218"
    assert _normalize_edb("MK4030996115218") == "4030996115218"
    assert _normalize_edb("mk 4030996115218") == "4030996115218"


def test_normalize_edb_rejects_wrong_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_edb("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_edb("40309961152189")  # 14 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_edb("403099611521A")


def test_parse_mk_date_handles_common_formats():
    assert _parse_mk_date("15.04.1992").isoformat() == "1992-04-15"
    assert _parse_mk_date("1992-04-15").isoformat() == "1992-04-15"
    assert _parse_mk_date("31/12/2010").isoformat() == "2010-12-31"
    assert _parse_mk_date("") is None
    assert _parse_mk_date(None) is None
    assert _parse_mk_date("not a date") is None


def test_classify_status_maps_localized_values():
    assert _classify_status("Активен") == "active"
    assert _classify_status("aktivna") == "active"
    assert _classify_status("Active") == "active"
    assert _classify_status("Избришан") == "ceased"
    assert _classify_status("Likvidiran") == "ceased"
    assert _classify_status("Стечај") == "ceased"
    assert _classify_status("Some other text") == "Some other text"
    assert _classify_status(None) is None


def test_parse_capital_amount_strips_currency_and_separators():
    amount, currency = _parse_capital("50.000.000,00 MKD")
    assert amount == 50000000.0
    assert currency == "MKD"
    amount, currency = _parse_capital("1.234.567,89 ден")
    assert amount == 1234567.89
    assert currency == "MKD"
    amount, currency = _parse_capital("500 EUR")
    assert amount == 500.0
    assert currency == "EUR"
    amount, currency = _parse_capital("")
    assert amount is None and currency is None
    amount, currency = _parse_capital(None)
    assert amount is None and currency is None


def test_parse_search_results_parses_label_value_table():
    html = """
    <html><body>
      <h1>Komercijalna Banka AD Skopje</h1>
      <table>
        <tr><td>Назив:</td><td>Komercijalna Banka AD Skopje</td></tr>
        <tr><td>ЕМБС:</td><td>4068916</td></tr>
        <tr><td>ЕДБ:</td><td>4030996115218</td></tr>
        <tr><td>Статус:</td><td>Активен</td></tr>
        <tr><td>Седиште:</td><td>Скопје, бул. Кочо Рацин 16</td></tr>
        <tr><td>Датум на регистрација:</td><td>27.10.1955</td></tr>
        <tr><td>Правна форма:</td><td>Акционерско друштво</td></tr>
        <tr><td>Основна главнина:</td><td>3.181.474.000,00 MKD</td></tr>
        <tr><td>Шифра на дејност:</td><td>6419</td></tr>
      </table>
    </body></html>
    """
    records = _parse_search_results(html)
    assert records, "expected at least one record"
    rec = records[0]
    assert rec["embs"] == "4068916"
    assert rec["edb"] == "4030996115218"
    assert "Komercijalna" in rec["name"]
    assert rec["status_raw"] == "Активен"
    assert "Скопје" in rec["address"]
    assert rec["incorporation_date"] == "27.10.1955"
    assert rec["activity_code"] == "6419"
    assert "3.181.474.000" in rec["capital"]


def test_parse_search_results_falls_back_to_loose_identifiers():
    html = """
    <html><body>
      <p>Some narrative with EMBS 4029895 inside and EDB 4030995188039
         buried somewhere.</p>
    </body></html>
    """
    records = _parse_search_results(html)
    assert records
    assert records[0]["embs"] == "4029895"
    assert records[0]["edb"] == "4030995188039"


def test_parse_search_results_empty_when_no_signals():
    assert _parse_search_results("") == []
    assert _parse_search_results("<html><body>Nothing here</body></html>") == []


def test_parse_filing_years_filters_outliers():
    html = "<p>Annual report 2019</p><p>2020 audit</p><p>2024 results</p><p>1899 footer</p>"
    years = _parse_filing_years(html)
    assert 2019 in years
    assert 2020 in years
    assert 2024 in years
    assert 1899 not in years


def test_adapter_static_attributes():
    adapter = MKAdapter()
    assert adapter.country_code == "MK"
    assert adapter.country_name == "North Macedonia"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = MKAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "4068916")


@pytest.mark.asyncio
async def test_fetch_financials_validates_embs():
    adapter = MKAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-an-embs")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = MKAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MK"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_komercijalna_banka_returns_details():
    adapter = MKAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "4068916"
    )
    # The portal may render a JS-only shell on some responses; we only
    # require that if the call succeeded with data, the shape is right.
    if details is None:
        pytest.skip("CRM portal returned no parseable data (likely JS-rendered)")
    assert details.country == "MK"
    assert details.id == "4068916"
    upper = details.name.upper()
    assert "KOMERCIJALNA" in upper or "КОМЕРЦИЈАЛНА" in upper


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_alkaloid_returns_details():
    adapter = MKAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "4029895"
    )
    if details is None:
        pytest.skip("CRM portal returned no parseable data (likely JS-rendered)")
    assert details.id == "4029895"
    upper = details.name.upper()
    assert "ALKALOID" in upper or "АЛКАЛОИД" in upper


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_edb_returns_details():
    adapter = MKAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "4030996115218"
    )
    if details is None:
        pytest.skip("CRM portal returned no parseable data (likely JS-rendered)")
    assert details.country == "MK"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_shaped_results():
    adapter = MKAdapter()
    matches = await adapter.search_by_name("Komercijalna Banka", limit=5)
    assert isinstance(matches, list)
    for m in matches:
        assert m.country == "MK"
        assert m.name
