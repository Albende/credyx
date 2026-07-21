from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.az import AZAdapter
from packages.adapters.az.adapter import (
    _distinctive_tokens,
    _extract_annual_reports,
    _normalize_voen,
    _parse_az_date,
    _slug_similarity,
    _slugify_az,
)
from packages.shared.models import FilingType, IdentifierType


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
    assert _parse_az_date("1995-11-24").isoformat() == "1995-11-24"
    assert _parse_az_date("15.04.1992").isoformat() == "1992-04-15"
    assert _parse_az_date("31/12/2010").isoformat() == "2010-12-31"
    assert _parse_az_date("") is None
    assert _parse_az_date(None) is None
    assert _parse_az_date("not a date") is None


def test_slugify_az_transliterates_diacritics():
    assert (
        _slugify_az('"KAPİTAL BANK" AÇIQ SƏHMDAR CƏMİYYƏTİ')
        == "kapital-bank-aciq-sehmdar-cemiyyeti"
    )
    assert (
        _slugify_az("AZƏRBAYCAN RESPUBLİKASININ DÖVLƏT NEFT ŞİRKƏTİ")
        == "azerbaycan-respublikasinin-dovlet-neft-sirketi"
    )


def test_slug_similarity_matches_register_name_to_issuer_slug():
    # Register name (genitive) vs Baku Stock Exchange issuer slug.
    socar_name = _distinctive_tokens(
        _slugify_az("AZƏRBAYCAN RESPUBLİKASININ DÖVLƏT NEFT ŞİRKƏTİ")
    )
    socar_issuer = _distinctive_tokens("azerbaycan-respublikasi-dovlet-neft-sirketi")
    assert _slug_similarity(socar_name, socar_issuer) >= 0.6

    # A different bank must not collide via shared legal-form words.
    kapital = _distinctive_tokens("kapital-bank-aciq-sehmdar-cemiyyeti")
    pasa = _distinctive_tokens("pasa-bank-aciq-sehmdar-cemiyyeti")
    assert _slug_similarity(kapital, pasa) < 0.6


def test_extract_annual_reports_scopes_to_annual_block():
    html = (
        '<h5>İllik maliyyə hesabatları:</h5>'
        '<div class="mb-5 pdf_grid">'
        '<div class="doc-card" title="2024 İllik Maliyyə hesabatı">'
        '<a href="https://www.bfb.az/issuer/rep-2024.pdf">yüklə</a></div>'
        '<div class="doc-card" title="2023 İllik Maliyyə hesabatı">'
        '<a href="/issuer/rep-2023.pdf">yüklə</a></div>'
        '</div>'
        '<h5>Yarımillik maliyyə hesabatları:</h5>'
        '<div class="doc-card" title="2024 Yarımillik">'
        '<a href="https://www.bfb.az/issuer/half-2024.pdf">yüklə</a></div>'
    )
    reports = _extract_annual_reports(html)
    assert reports == [
        (2024, "https://www.bfb.az/issuer/rep-2024.pdf"),
        (2023, "https://www.bfb.az/issuer/rep-2023.pdf"),
    ]


def test_extract_annual_reports_empty_when_no_section():
    assert _extract_annual_reports("") == []
    assert _extract_annual_reports("<html><body>no reports</body></html>") == []


@pytest.mark.asyncio
async def test_lookup_rejects_non_vat_identifier():
    adapter = AZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "9900003871"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = AZAdapter()
    matches = await adapter.search_by_name("AZERCELL")
    assert matches
    top = matches[0]
    assert top.country == "AZ"
    assert top.id.isdigit() and len(top.id) == 10
    assert "AZERCELL" in top.name.upper()


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
    assert details.capital_amount and details.capital_amount > 0
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
    assert "PA" in details.name.upper()  # PAŞA / PASHA / ПАША


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_socar_returns_listed_filings():
    adapter = AZAdapter()
    filings = await adapter.fetch_financials("9900003871", years=3)
    assert filings
    first = filings[0]
    assert first.company_id == "9900003871"
    assert first.type == FilingType.ANNUAL_REPORT
    assert first.currency == "AZN"
    assert first.source_url and "bfb.az" in first.source_url
    assert first.document_url and first.document_url.lower().endswith(".pdf")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_empty_for_non_listed():
    adapter = AZAdapter()
    # Azercell is a real active taxpayer but is not a Baku Stock Exchange issuer.
    assert await adapter.fetch_financials("9900022721") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = AZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AZ"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30
    assert health.capabilities["lookup"] is True
