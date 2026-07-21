from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.am import AMAdapter
from packages.adapters.am.adapter import (
    _classify_status,
    _legal_form_from_name,
    _normalize_reg_number,
    _normalize_tin,
    _parse_am_date,
    _parse_company_card,
    _parse_search_hits,
)
from packages.shared.models import IdentifierType


def test_normalize_tin_strips_prefix_and_whitespace():
    assert _normalize_tin("00024873") == "00024873"
    assert _normalize_tin(" 00024873 ") == "00024873"
    assert _normalize_tin("AM00024873") == "00024873"
    assert _normalize_tin("am 00024873") == "00024873"
    assert _normalize_tin("0002-4873") == "00024873"


def test_normalize_tin_rejects_invalid_lengths():
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("000248739")  # 9 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("0002ABCD")


def test_normalize_reg_number_accepts_common_shapes():
    assert _normalize_reg_number("286.120.1110041") == "286.120.1110041"
    assert _normalize_reg_number(" 222-555-12345 ") == "222-555-12345"
    assert _normalize_reg_number("12345") == "12345"
    with pytest.raises(InvalidIdentifierError):
        _normalize_reg_number("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_reg_number("contains spaces and letters!!")


def test_parse_am_date_handles_common_formats():
    assert _parse_am_date("15-01-2020").isoformat() == "2020-01-15"
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


def test_classify_status_reads_register_negative_phrasing_as_active():
    text = (
        "There is no information recorded in the unified state register "
        "regarding being in the process of liquidation or the termination "
        "of activity"
    )
    assert _classify_status(text) == "active"


def test_legal_form_from_name():
    assert _legal_form_from_name('"UCOM" CJSC') == "CJSC"
    assert _legal_form_from_name('"ARDSHIN" LLC') == "LLC"
    assert _legal_form_from_name("SOME OJSC") == "OJSC"
    assert _legal_form_from_name("no suffix here") is None


def test_parse_search_hits_extracts_id_and_name():
    html = """
    <section>
      <article class="application-view-article company-search-result">
        <a href="/en/companies/37191802"><h4>&quot;UCOM&quot; CJSC</h4></a>
      </article>
      <article class="application-view-article company-search-result">
        <a href="/en/companies/55415850"><h4>&quot;ARDSHIN&quot; LLC</h4></a>
      </article>
    </section>
    """
    hits = _parse_search_hits(html)
    assert ("37191802", '"UCOM" CJSC') in hits
    assert ("55415850", '"ARDSHIN" LLC') in hits


def test_parse_company_card_reads_definition_list():
    html = """
    <div class="border company-title">
      <h4>&quot;UCOM&quot; CJSC</h4>
      <dl class="detail-list">
        <dt>Company Status</dt>
        <dd>There is no information recorded regarding liquidation</dd>
        <dt>Registration number</dt><dd>286.120.1110041</dd>
        <dt>Registration date</dt><dd>15-01-2020</dd>
        <dt>Registration Body</dt><dd>RA MoJ state register</dd>
        <dt>Tax id</dt><dd>00024873</dd>
        <dt>Unique identifier</dt><dd>37191802</dd>
        <dt>Address</dt><dd>Yerevan, Manandyan 33/8</dd>
      </dl>
    </div>
    """
    record = _parse_company_card(html)
    assert "UCOM" in record["name"]
    assert record["reg_number"] == "286.120.1110041"
    assert record["registration_date"] == "15-01-2020"
    assert record["tin"] == "00024873"
    assert record["unique_id"] == "37191802"
    assert "Yerevan" in record["address"]
    assert "no information recorded" in record["status_raw"].lower()


def test_parse_company_card_empty_without_name():
    assert _parse_company_card("") == {}
    assert _parse_company_card("<html><body>No data</body></html>") == {}


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = AMAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "00024873")


@pytest.mark.asyncio
async def test_fetch_financials_not_implemented():
    adapter = AMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.fetch_financials("00024873")


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
async def test_lookup_ucom_by_tin_returns_company_details():
    adapter = AMAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "00024873"
    )
    assert details is not None
    assert details.country == "AM"
    assert details.id == "00024873"
    assert "UCOM" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ucom_by_reg_number_returns_company_details():
    adapter = AMAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "286.120.1110041"
    )
    assert details is not None
    assert "UCOM" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = AMAdapter()
    matches = await adapter.search_by_name("UCOM", limit=10)
    assert isinstance(matches, list)
    assert matches
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
