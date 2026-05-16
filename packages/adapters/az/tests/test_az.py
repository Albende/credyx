from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.az import AZAdapter
from packages.adapters.az.adapter import (
    _classify_status,
    _extract_taxpayer_record,
    _normalize_voen,
    _parse_az_date,
)
from packages.shared.models import IdentifierType


def test_normalize_voen_strips_prefix_and_whitespace():
    assert _normalize_voen("9900003871") == "9900003871"
    assert _normalize_voen(" 9900003871 ") == "9900003871"
    assert _normalize_voen("AZ9900003871") == "9900003871"
    assert _normalize_voen("az 9900003871") == "9900003871"
    assert _normalize_voen("9900-0038-71") == "9900003871"


def test_normalize_voen_rejects_invalid_lengths():
    with pytest.raises(InvalidIdentifierError):
        _normalize_voen("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_voen("99000038711")  # 11 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_voen("99000ABCDE")


def test_parse_az_date_handles_common_formats():
    assert _parse_az_date("15.04.1992").isoformat() == "1992-04-15"
    assert _parse_az_date("2001-09-30").isoformat() == "2001-09-30"
    assert _parse_az_date("31/12/2010").isoformat() == "2010-12-31"
    assert _parse_az_date("") is None
    assert _parse_az_date(None) is None
    assert _parse_az_date("not a date") is None


def test_classify_status_maps_localized_values():
    assert _classify_status("Fəal") == "active"
    assert _classify_status("aktivdir") == "active"
    assert _classify_status("Действующее") == "active"
    assert _classify_status("Ləğv edilib") == "inactive"
    assert _classify_status("закрыт") == "inactive"
    assert _classify_status(None) is None


def test_extract_taxpayer_record_parses_two_column_table():
    html = """
    <html><body>
      <table>
        <tr><td>Vergi ödəyicisinin adı:</td>
            <td>"AZƏRBAYCAN RESPUBLİKASI DÖVLƏT NEFT ŞİRKƏTİ"</td></tr>
        <tr><td>VÖEN:</td><td>9900003871</td></tr>
        <tr><td>Vəziyyət:</td><td>Fəal</td></tr>
        <tr><td>Ünvan:</td><td>Bakı şəhəri, Heydər Əliyev pr. 73</td></tr>
        <tr><td>Qeydiyyat tarixi:</td><td>15.04.1992</td></tr>
        <tr><td>Təşkilati-hüquqi forma:</td><td>Açıq Səhmdar Cəmiyyəti</td></tr>
      </table>
    </body></html>
    """
    record = _extract_taxpayer_record(html)
    assert "DÖVLƏT NEFT ŞİRKƏTİ" in record["name"]
    assert record["status_raw"] == "Fəal"
    assert "Bakı" in record["address"]
    assert record["registration_date"] == "15.04.1992"
    assert "Səhmdar" in record["legal_form"]


def test_extract_taxpayer_record_empty_when_no_table():
    assert _extract_taxpayer_record("") == {}
    assert _extract_taxpayer_record("<html><body>No data</body></html>") == {}


@pytest.mark.asyncio
async def test_search_by_name_not_implemented():
    adapter = AZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("SOCAR")


@pytest.mark.asyncio
async def test_fetch_financials_not_implemented():
    adapter = AZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.fetch_financials("9900003871")


@pytest.mark.asyncio
async def test_lookup_rejects_non_vat_identifier():
    adapter = AZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "9900003871"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_socar_returns_company_details():
    adapter = AZAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "9900003871"
    )
    assert details is not None
    assert details.country == "AZ"
    assert details.id == "9900003871"
    assert details.name
    # Match either Latin or Cyrillic transliteration of "Neft".
    assert any(
        token in details.name.upper() for token in ("NEFT", "НЕФТ", "SOCAR")
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_pasha_bank():
    adapter = AZAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "1700767721"
    )
    assert details is not None
    assert details.id == "1700767721"
    assert "PASHA" in details.name.upper() or "ПАША" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = AZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AZ"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30
