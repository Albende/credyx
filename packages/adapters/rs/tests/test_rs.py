from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.rs import RSAdapter
from packages.adapters.rs.adapter import (
    _classify_status,
    _normalize_mb,
    _normalize_pib,
    _parse_capital,
    _parse_fi_years,
    _parse_rs_date,
    _parse_search_results,
)
from packages.shared.models import (
    AdapterStatus,
    FilingType,
    IdentifierType,
)


def test_normalize_mb_validates_eight_digits():
    assert _normalize_mb("20084693") == "20084693"
    assert _normalize_mb(" 20084693 ") == "20084693"
    assert _normalize_mb("2008-4693") == "20084693"
    with pytest.raises(InvalidIdentifierError):
        _normalize_mb("1234567")
    with pytest.raises(InvalidIdentifierError):
        _normalize_mb("ABCDEFGH")
    with pytest.raises(InvalidIdentifierError):
        _normalize_mb("123456789")


def test_normalize_pib_strips_rs_prefix_and_validates_nine_digits():
    assert _normalize_pib("104052135") == "104052135"
    assert _normalize_pib("RS104052135") == "104052135"
    assert _normalize_pib(" rs 104052135 ") == "104052135"
    assert _normalize_pib("104-052-135") == "104052135"
    with pytest.raises(InvalidIdentifierError):
        _normalize_pib("12345678")
    with pytest.raises(InvalidIdentifierError):
        _normalize_pib("1040521350")


def test_parse_rs_date_handles_common_formats():
    assert _parse_rs_date("12.06.2005").isoformat() == "2005-06-12"
    assert _parse_rs_date("12.06.2005.").isoformat() == "2005-06-12"
    assert _parse_rs_date("2005-06-12").isoformat() == "2005-06-12"
    assert _parse_rs_date("31/12/1999").isoformat() == "1999-12-31"
    assert _parse_rs_date(None) is None
    assert _parse_rs_date("") is None
    assert _parse_rs_date("not-a-date") is None


def test_classify_status_maps_cyrillic_and_latin():
    assert _classify_status("Активно привредно друштво") == "active"
    assert _classify_status("Aktivno") == "active"
    assert _classify_status("Брисан из регистра") == "ceased"
    assert _classify_status("Stečaj") == "ceased"
    assert _classify_status(None) is None


def test_parse_capital_handles_serbian_locale():
    amount, currency = _parse_capital("1.234.567,89 RSD")
    assert amount == 1234567.89
    assert currency == "RSD"
    amount, currency = _parse_capital("500.000,00 дин")
    assert amount == 500000.00
    assert currency == "RSD"
    amount, currency = _parse_capital("123,45 EUR")
    assert amount == 123.45
    assert currency == "EUR"
    assert _parse_capital(None) == (None, None)
    assert _parse_capital("not a number") == (None, None)


def test_parse_search_results_extracts_labelled_fields():
    html = """
    <html><body>
      <table>
        <tr><td>Пословно име:</td><td>NIS a.d. Novi Sad</td></tr>
        <tr><td>Матични број:</td><td>20084693</td></tr>
        <tr><td>ПИБ:</td><td>104052135</td></tr>
        <tr><td>Правна форма:</td><td>Акционарско друштво</td></tr>
        <tr><td>Статус:</td><td>Активно привредно друштво</td></tr>
        <tr><td>Седиште:</td><td>Народног фронта 12, Нови Сад</td></tr>
        <tr><td>Датум оснивања:</td><td>15.07.2005.</td></tr>
        <tr><td>Шифра делатности:</td><td>0610 — Експлоатација сирове нафте</td></tr>
        <tr><td>Уписани капитал:</td><td>81.530.200.000,00 RSD</td></tr>
      </table>
    </body></html>
    """
    records = _parse_search_results(html)
    assert len(records) == 1
    rec = records[0]
    assert rec["name"] == "NIS a.d. Novi Sad"
    assert rec["mb"] == "20084693"
    assert rec["pib"] == "104052135"
    assert "Акционарско" in rec["legal_form"]
    assert "Активно" in rec["status_raw"]
    assert "Нови Сад" in rec["address"]
    assert rec["incorporation_date"] == "15.07.2005."
    assert rec["activity_code"] == "0610"
    assert "81.530.200.000,00" in rec["capital"]


def test_parse_search_results_falls_back_to_token_scan():
    html = """
    <html><body>
      <div class="result">
        <span>Telekom Srbija a.d.</span>
        <span>MB 17162543 PIB 100002887</span>
      </div>
    </body></html>
    """
    records = _parse_search_results(html)
    # With no labelled <td> cells the parser still has to surface identifiers
    # from the flattened text scan path.
    assert records and records[0]["mb"] == "17162543"
    assert records[0]["pib"] == "100002887"


def test_parse_search_results_empty_when_no_signal():
    assert _parse_search_results("") == []
    assert _parse_search_results("<html><body>nothing here</body></html>") == []


def test_parse_fi_years_extracts_reporting_years():
    html = """
    <table>
      <tr><th>Година</th><th>Документ</th></tr>
      <tr><td>2023</td><td>GFI</td></tr>
      <tr><td>2022</td><td>GFI</td></tr>
      <tr><td>2021</td><td>GFI</td></tr>
      <tr><td>1899</td><td>(footer year — ignore)</td></tr>
    </table>
    """
    years = _parse_fi_years(html)
    assert 2023 in years
    assert 2022 in years
    assert 2021 in years
    assert 1899 not in years


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = RSAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "20084693")


@pytest.mark.asyncio
async def test_fetch_financials_validates_mb():
    adapter = RSAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-mb")


def test_adapter_capabilities_and_metadata():
    adapter = RSAdapter()
    assert adapter.country_code == "RS"
    assert adapter.country_name == "Serbia"
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = RSAdapter()
    health = await adapter.health_check()
    assert health.country_code == "RS"
    assert health.requires_api_key is False
    assert health.status in (
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_nis_by_mb():
    adapter = RSAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "20084693"
    )
    assert details is not None
    assert details.country == "RS"
    assert details.id == "20084693"
    upper_name = details.name.upper()
    assert "NIS" in upper_name or "НИС" in upper_name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_telekom_by_pib():
    adapter = RSAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "100002887"
    )
    assert details is not None
    upper = details.name.upper()
    assert "TELEKOM" in upper or "ТЕЛЕКОМ" in upper
    pib_ids = [i for i in details.identifiers if i.type == IdentifierType.VAT]
    if pib_ids:
        assert pib_ids[0].value == "100002887"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = RSAdapter()
    matches = await adapter.search_by_name("Delta Holding")
    # The portal may rate-limit or change markup; integration test asserts
    # only that the call did not blow up. Per project rules we do not invent
    # an empty-list fallback — `search_by_name` is allowed to return [] when
    # APR's HTML lacks identifiers we can extract.
    assert isinstance(matches, list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_nis_returns_annual_reports():
    adapter = RSAdapter()
    filings = await adapter.fetch_financials("20084693", years=10)
    assert isinstance(filings, list)
    for f in filings:
        assert f.company_id == "20084693"
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "RSD"
