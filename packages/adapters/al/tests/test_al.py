from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.al import ALAdapter
from packages.adapters.al.adapter import (
    _classify_status,
    _extract_company_record,
    _extract_document_links,
    _extract_search_cards,
    _extract_year_series,
    _normalize_nipt,
    _parse_al_date,
    _parse_amount,
)
from packages.shared.models import IdentifierType

# Real, currently-resolving NIPTs on opencorporates.al (AIS open-data mirror).
_ONE_ALBANIA = "J61814094W"  # ex Telekom Albania
_BKT = "J62001011Q"  # Banka Kombëtare Tregtare
_VODAFONE = "K11715005L"  # Vodafone Albania


def test_normalize_nipt_accepts_canonical_form():
    assert _normalize_nipt("J61814094W") == "J61814094W"
    assert _normalize_nipt(" j61814094w ") == "J61814094W"
    assert _normalize_nipt("J 61814094 W") == "J61814094W"
    assert _normalize_nipt("J-61814094-W") == "J61814094W"


def test_normalize_nipt_strips_eu_vat_prefix():
    assert _normalize_nipt("ALJ61814094W") == "J61814094W"
    assert _normalize_nipt("al j61814094w") == "J61814094W"


def test_normalize_nipt_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("123456789")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("J6181409W")  # too short
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("J618140940")  # ends with digit not letter
    with pytest.raises(InvalidIdentifierError):
        _normalize_nipt("961814094W")  # starts with digit not letter


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


def test_parse_amount_handles_albanian_number_format():
    assert _parse_amount("863 826 822,00") == 863826822.0
    assert _parse_amount("-539 854 000,00") == -539854000.0
    assert _parse_amount("100 000,00") == 100000.0
    assert _parse_amount("1.500.000,50") == 1500000.5
    assert _parse_amount("") is None
    assert _parse_amount(None) is None
    assert _parse_amount("no numbers here") is None


def test_extract_company_record_parses_detail_page():
    html = """
    <html><body>
      <h2 class="title-divider"><span>TELEKOM ALBANIA Sh.A.</span></h2>
      <table>
        <tr><th>Tax Registration Number:</th><td>J61814094W</td></tr>
        <tr><th>Status:</th><td>Aktiv</td></tr>
        <tr><th>Address:</th><td>Tiranë, Rruga Sami Frashëri</td></tr>
        <tr><th>Foundation Year:</th><td>15/04/2000</td></tr>
        <tr><th>Legal Form:</th><td>Shoqëri Aksionare SH.A</td></tr>
        <tr><th>Initial Capital:</th><td>1 500 000 000,00</td></tr>
        <tr><th>Administrators:</th><td>John Doe</td></tr>
        <tr><th>District:</th><td>Tiranë</td></tr>
      </table>
    </body></html>
    """
    record = _extract_company_record(html)
    assert "TELEKOM" in record["name"].upper()
    assert record["nipt"] == "J61814094W"
    assert record["status_raw"] == "Aktiv"
    assert "Tiranë" in record["address"]
    assert record["registration_date"] == "15/04/2000"
    assert "Aksionare" in record["legal_form"]
    assert "1 500 000 000" in record["capital"]
    assert record["director"] == "John Doe"
    assert record["district"] == "Tiranë"


def test_extract_company_record_empty_when_no_table():
    assert _extract_company_record("") == {}
    assert _extract_company_record("<html><body>No data</body></html>") == {}


def test_extract_search_cards_picks_name_nipt_address():
    html = """
    <html><body>
      <div class="card">
        <h4 class="mb-0">VODAFONE ALBANIA</h4>
        <a href="/sq/nipt/k11715005l">K11715005L</a>
        <span><i class="fa fa-map-marker"></i> Tirane</span>
        Aktiv
      </div>
      <h4 class="mb-0">VODAFONE M-PESA</h4>
      <a href="/sq/nipt/l31527001n">L31527001N</a>
    </body></html>
    """
    cards = _extract_search_cards(html)
    names = {c["name"] for c in cards}
    nipts = {c["nipt"] for c in cards}
    assert "VODAFONE ALBANIA" in names
    assert "VODAFONE M-PESA" in names
    assert "K11715005L" in nipts
    assert "L31527001N" in nipts
    vodafone = next(c for c in cards if c["nipt"] == "K11715005L")
    assert vodafone["address"] == "Tirane"


def test_extract_year_series_reads_annual_figures():
    html = (
        "Annual Turnover (ALL Lekë) 2023:80 511 702,00<br>"
        "Annual Turnover (ALL Lekë) 2022:61 028 762,00<br>"
    )
    series = _extract_year_series(html, r"Annual Turnover \(ALL")
    assert series[2023] == 80511702.0
    assert series[2022] == 61028762.0


def test_extract_document_links_maps_year_to_href():
    html = (
        '<a href="/documents/bilanci/abc2010.pdf.pdf"> Pasqyrat Financiare 2010</a>'
        '<a href="/documents/bilanci/xyz2011.xls.xls"> Pasqyra financiare 2011</a>'
    )
    docs = _extract_document_links(html)
    assert docs[2010].endswith("abc2010.pdf.pdf")
    assert docs[2011].endswith("xyz2011.xls.xls")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = ALAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, _ONE_ALBANIA)


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_nipt():
    adapter = ALAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "BADVALUE")


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
async def test_lookup_one_albania_returns_company_details():
    adapter = ALAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, _ONE_ALBANIA)
    if details is None:
        pytest.skip("opencorporates.al returned no record — site may have changed")
    assert details.country == "AL"
    assert details.id == _ONE_ALBANIA
    assert details.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bkt_returns_company_details():
    adapter = ALAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, _BKT)
    if details is None:
        pytest.skip("opencorporates.al returned no record for BKT — site may have changed")
    assert details.id == _BKT
    upper = details.name.upper()
    assert "BANK" in upper or "BKT" in upper or "TREGT" in upper


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_real_filings():
    adapter = ALAdapter()
    filings = await adapter.fetch_financials(_BKT, years=3)
    if not filings:
        pytest.skip("opencorporates.al returned no filings — site may have changed")
    assert len(filings) <= 3
    for f in filings:
        assert f.company_id == _BKT
        assert f.currency == "ALL"
        assert 1990 <= f.year <= 2100
        # A filing must carry real data: structured figures and/or a document.
        assert f.structured_data or f.document_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_shape():
    adapter = ALAdapter()
    matches = await adapter.search_by_name("Vodafone", limit=5)
    assert isinstance(matches, list)
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
