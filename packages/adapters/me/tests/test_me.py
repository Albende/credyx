from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.me import MEAdapter
from packages.adapters.me.adapter import (
    _classify_filing,
    _extract_legal_form,
    _name_tokens,
    _normalize_me_id,
    _parse_financial_docs,
    _parse_issuer_detail,
    _strip_diacritics,
)
from packages.shared.models import FilingType, IdentifierType


def test_normalize_strips_me_prefix():
    assert _normalize_me_id("ME 02289377", label="PIB") == "02289377"
    assert _normalize_me_id("02002230", label="PIB") == "02002230"


def test_normalize_rejects_wrong_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_me_id("1234567", label="MB")
    with pytest.raises(InvalidIdentifierError):
        _normalize_me_id("123456789", label="MB")


def test_normalize_rejects_non_digits():
    with pytest.raises(InvalidIdentifierError):
        _normalize_me_id("ABCDEFGH", label="PIB")


def test_strip_diacritics_handles_montenegrin():
    assert _strip_diacritics("Plantaže") == "Plantaze"
    assert _strip_diacritics("Nikšić") == "Niksic"
    assert _strip_diacritics("Čačak Š") == "Cacak S"


def test_legal_form_recognized():
    assert _extract_legal_form("Crnogorski Telekom A.D.") == "AD"
    assert _extract_legal_form("Neka Firma d.o.o.") == "DOO"
    assert _extract_legal_form("Bezimena Kompanija") is None


def test_name_tokens_drops_stopwords():
    tokens = _name_tokens('"CRNOGORSKI TELEKOM" A.D. PODGORICA')
    assert "TELEKOM" in tokens
    assert "CRNOGORSKI" in tokens
    assert "AD" not in tokens
    assert "PODGORICA" not in tokens


def test_parse_issuer_detail_extracts_fields():
    sample = (
        '<td class="td_header_row" colspan="2">CRNOGORSKI TELEKOM AD PODGORICA</td>'
        '<td class="td_color2_02">Adresa</td>'
        '<td class="td_color1_02 txt_right">MOSKOVSKA 29, 81000 PODGORICA</td>'
        '<td class="td_color2_01">Matični broj</td>'
        '<td class="td_color1_01 txt_right">2289377</td>'
        '<td class="td_color2_01">Šifra djelatnosti</td>'
        '<td class="td_color1_01 txt_right">6110 Kablovske telekomunikacije</td>'
        "ISIN </td><td>METECGRA8PG0"
    )
    info = _parse_issuer_detail(sample)
    assert info["name"] == "CRNOGORSKI TELEKOM AD PODGORICA"
    assert info["address"] == "MOSKOVSKA 29, 81000 PODGORICA"
    assert info["mb"] == "02289377"
    assert info["nace"].startswith("6110")
    assert info["isin"] == "METECGRA8PG0"


def test_parse_financial_docs_only_financial_section():
    sample = (
        "<h1>CRNOGORSKI TELEKOM AD PODGORICA</h1>"
        "<h1>Finansijski i revizorski izvještaji</h1>"
        '<a href="/upload/documents/issuer/TECG/god.pdf">'
        "Godišnji izvještaj za 2025. godinu (pdf)</a>"
        '<a href="/upload/documents/issuer/TECG/rev.pdf">'
        "Revizorski izvještaj za 2024. godinu (pdf)</a>"
        "<h1>Objave i odluke</h1>"
        '<a href="/upload/documents/issuer/TECG/poziv.pdf">'
        "Poziv za sjednicu Skupštine 2026</a>"
    )
    docs = _parse_financial_docs(sample)
    years = {d["year"]: d["type"] for d in docs}
    assert years[2025] == FilingType.ANNUAL_REPORT
    assert years[2024] == FilingType.AUDIT_REPORT
    assert all("poziv" not in d["href"] for d in docs)


def test_classify_filing():
    assert _classify_filing("Revizorski izvještaj za 2024.") == FilingType.AUDIT_REPORT
    assert (
        _classify_filing("Godišnji izvještaj za 2025. godinu")
        == FilingType.ANNUAL_REPORT
    )
    assert (
        _classify_filing("Finansijski izvještaj za period 01.01-30.06.2025.")
        == FilingType.BALANCE_SHEET
    )


def test_adapter_metadata():
    a = MEAdapter()
    assert a.country_code == "ME"
    assert IdentifierType.VAT in a.identifier_types
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert a.primary_identifier == IdentifierType.VAT
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = MEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ME"
    assert health.name == "Montenegro"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_telekom():
    adapter = MEAdapter()
    matches = await adapter.search_by_name("Crnogorski Telekom", limit=5)
    assert matches
    for m in matches:
        assert m.country == "ME"
    assert any("TELEKOM" in m.name.upper() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_pib_telekom():
    adapter = MEAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "02289377")
    assert details is not None
    assert details.country == "ME"
    assert "TELEKOM" in details.name.upper()
    assert any(i.value.endswith("02289377") for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_mb_epcg():
    adapter = MEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "02002230"
    )
    assert details is not None
    assert details.country == "ME"
    assert "ELEKTROPRIVREDA" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_issuer():
    adapter = MEAdapter()
    filings = await adapter.fetch_financials("02289377", years=3)
    assert filings
    for f in filings:
        assert f.currency == "EUR"
        assert f.source_url and "mnse.me" in f.source_url
        assert f.document_url and f.document_url.startswith("https://www.mnse.me/")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_unknown_pib_returns_empty():
    adapter = MEAdapter()
    filings = await adapter.fetch_financials("99999999", years=2)
    assert filings == []


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = MEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "02289377")
