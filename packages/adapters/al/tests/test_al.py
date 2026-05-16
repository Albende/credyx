from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.al import ALAdapter
from packages.adapters.al.adapter import (
    _classify_status,
    _extract_company_record,
    _extract_search_rows,
    _normalize_nipt,
    _parse_al_date,
    _parse_capital_amount,
)
from packages.shared.models import IdentifierType


def test_normalize_nipt_accepts_canonical_form():
    assert _normalize_nipt("J91904005U") == "J91904005U"
    assert _normalize_nipt(" j91904005u ") == "J91904005U"
    assert _normalize_nipt("J 91904005 U") == "J91904005U"
    assert _normalize_nipt("J-91904005-U") == "J91904005U"


def test_normalize_nipt_strips_eu_vat_prefix():
    assert _normalize_nipt("ALJ91904005U") == "J91904005U"
    assert _normalize_nipt("al j91904005u") == "J91904005U"


def test_normalize_nipt_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("123456789")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("J9190400U")  # too short
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("J919040050")  # ends with digit not letter
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("991904005U")  # starts with digit not letter


def test_parse_al_date_handles_common_formats():
    assert _parse_al_date("15/04/1992").isoformat() == "1992-04-15"
    assert _parse_al_date("15.04.1992").isoformat() == "1992-04-15"
    assert _parse_al_date("2001-09-30").isoformat() == "2001-09-30"
    assert _parse_al_date("") is None
    assert _parse_al_date(None) is None
    assert _parse_al_date("not a date") is None


def test_classify_status_maps_localized_values():
    assert _classify_status("Aktiv") == "active"
    assert _classify_status("I REGJISTRUAR") == "active"
    assert _classify_status("Active") == "active"
    assert _classify_status("Çregjistruar") == "inactive"
    assert _classify_status("Në likuidim") == "inactive"
    assert _classify_status("Pezulluar") == "inactive"
    assert _classify_status("Liquidated") == "inactive"
    assert _classify_status(None) is None


def test_parse_capital_amount_strips_currency_and_separators():
    assert _parse_capital_amount("100.000 ALL") == 100000.0
    assert _parse_capital_amount("ALL 1.500.000,50") == 1500000.5
    assert _parse_capital_amount("100,000") == 100.0  # comma-as-decimal default
    assert _parse_capital_amount("") is None
    assert _parse_capital_amount(None) is None
    assert _parse_capital_amount("no numbers here") is None


def test_extract_company_record_parses_two_column_table():
    html = """
    <html><body>
      <h1>Telekom Albania</h1>
      <table>
        <tr><td>Emri i subjektit:</td><td>TELEKOM ALBANIA Sh.A.</td></tr>
        <tr><td>NIPT:</td><td>J91904005U</td></tr>
        <tr><td>Statusi:</td><td>Aktiv</td></tr>
        <tr><td>Adresa:</td><td>Tiranë, Rruga Sami Frashëri</td></tr>
        <tr><td>Data e regjistrimit:</td><td>15/04/2000</td></tr>
        <tr><td>Forma ligjore:</td><td>Shoqëri Aksionere</td></tr>
        <tr><td>Kapitali:</td><td>1.500.000.000 ALL</td></tr>
        <tr><td>Administrator:</td><td>John Doe</td></tr>
      </table>
    </body></html>
    """
    record = _extract_company_record(html)
    assert "TELEKOM" in record["name"].upper()
    assert record["nipt"] == "J91904005U"
    assert record["status_raw"] == "Aktiv"
    assert "Tiranë" in record["address"]
    assert record["registration_date"] == "15/04/2000"
    assert "Aksionere" in record["legal_form"]
    assert "1.500.000.000" in record["capital"]
    assert record["director"] == "John Doe"


def test_extract_company_record_empty_when_no_table():
    assert _extract_company_record("") == {}
    assert _extract_company_record("<html><body>No data</body></html>") == {}


def test_extract_company_record_falls_back_to_heading():
    html = "<html><body><h1>Banka Kombëtare Tregtare</h1><p>no table</p></body></html>"
    record = _extract_company_record(html)
    assert record.get("name") == "Banka Kombëtare Tregtare"


def test_extract_search_rows_picks_name_and_nipt():
    html = """
    <html><body><table>
      <tr><th>Emri</th><th>NIPT</th><th>Statusi</th></tr>
      <tr><td>TELEKOM ALBANIA Sh.A.</td><td>J91904005U</td><td>Aktiv</td></tr>
      <tr><td>BANKA KOMBËTARE TREGTARE Sh.A.</td><td>J61824032O</td><td>Aktiv</td></tr>
    </table></body></html>
    """
    rows = _extract_search_rows(html)
    names = {r["name"] for r in rows}
    nipts = {r["nipt"] for r in rows}
    assert "TELEKOM ALBANIA Sh.A." in names
    assert "BANKA KOMBËTARE TREGTARE Sh.A." in names
    assert "J91904005U" in nipts
    assert "J61824032O" in nipts


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = ALAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "J91904005U")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_nipt():
    adapter = ALAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "BADVALUE")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = ALAdapter()
    # AL has no centrally-published filings, but per the project rules we
    # return [] (no mock, no 501) so the API contract stays stable.
    result = await adapter.fetch_financials("J91904005U")
    assert result == []


def test_adapter_static_attributes():
    adapter = ALAdapter()
    assert adapter.country_code == "AL"
    assert adapter.country_name == "Albania"
    assert adapter.primary_identifier == IdentifierType.VAT
    assert IdentifierType.VAT in adapter.identifier_types
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_telekom_albania_returns_company_details():
    adapter = ALAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "J91904005U"
    )
    # Live registry markup can change without notice; we only assert that
    # when a record is returned, its country and identifier line up.
    if details is None:
        pytest.skip("QKB returned no record for probe NIPT — site may have changed")
    assert details.country == "AL"
    assert details.id == "J91904005U"
    assert details.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bkt_returns_company_details():
    adapter = ALAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "J61824032O"
    )
    if details is None:
        pytest.skip("QKB returned no record for BKT — site may have changed")
    assert details.id == "J61824032O"
    upper = details.name.upper()
    assert "BANK" in upper or "BKT" in upper or "TREGT" in upper


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_shape():
    adapter = ALAdapter()
    matches = await adapter.search_by_name("Telekom", limit=5)
    assert isinstance(matches, list)
    # Don't assert non-empty: the public search may require a JS-rendered
    # form post; we only require the call succeeds and shape is correct.
    for m in matches:
        assert m.country == "AL"
        assert m.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = ALAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AL"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30
