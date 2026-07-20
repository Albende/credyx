from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.kz import KZAdapter
from packages.shared.models import FilingType, IdentifierType

# Real Kazakhstan test companies (verified via adata.kz + DFO depository).
KMG_BIN = "020240000555"        # АО "НК "КазМунайГаз" — non-financial, form 665
KASPI_BIN = "971240001315"      # Kaspi — financial org, IFRS reports
UNLISTED_BIN = "980440000757"   # ТОО "TESM Company" — not a public-interest filer


def test_bin_normalizer_strips_prefix_and_validates():
    from packages.adapters.kz.adapter import _normalize_bin

    assert _normalize_bin("020240000555") == "020240000555"
    assert _normalize_bin("KZ020240000555") == "020240000555"
    assert _normalize_bin("020 240 000 555") == "020240000555"
    assert _normalize_bin("020-240-000-555") == "020240000555"


def test_bin_normalizer_rejects_invalid():
    from packages.adapters.kz.adapter import _normalize_bin

    with pytest.raises(InvalidIdentifierError):
        _normalize_bin("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_bin("ABCDEF000327")


def test_reg_date_parser():
    from packages.adapters.kz.adapter import _parse_reg_date
    from datetime import date

    assert _parse_reg_date("27-02-2002 (24 года 4 месяца)") == date(2002, 2, 27)
    assert _parse_reg_date("") is None
    assert _parse_reg_date(None) is None


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_id_type():
    adapter = KZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.SIREN, KMG_BIN)


@pytest.mark.asyncio
async def test_search_empty_name_returns_empty():
    adapter = KZAdapter()
    assert await adapter.search_by_name("   ") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = KZAdapter()
    matches = await adapter.search_by_name("КазМунайГаз", limit=5)
    assert matches
    top = matches[0]
    assert top.country == "KZ"
    assert top.id.isdigit() and len(top.id) == 12
    assert top.name
    assert top.identifiers[0].label == "BIN"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_kazmunaygas_bin():
    adapter = KZAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, KMG_BIN)
    assert details is not None
    assert details.country == "KZ"
    assert details.id == KMG_BIN
    assert "КАЗМУНАЙГАЗ" in details.name.upper()
    assert details.incorporation_date is not None
    assert details.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_bin_returns_none():
    adapter = KZAdapter()
    assert await adapter.lookup_by_identifier(IdentifierType.VAT, "000000000000") is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_dfo_reports():
    adapter = KZAdapter()
    filings = await adapter.fetch_financials(KMG_BIN, years=3)
    assert filings
    for f in filings:
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "KZT"
        assert f.company_id == KMG_BIN
        assert f.source_url and "opi.dfo.kz" in f.source_url
        assert f.structured_data and f.structured_data["report_id"]
    years = [f.year for f in filings]
    assert years == sorted(years, reverse=True)
    assert len(set(years)) == len(years)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_empty_for_non_public_interest():
    adapter = KZAdapter()
    assert await adapter.fetch_financials(UNLISTED_BIN, years=3) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_all_capabilities():
    adapter = KZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "KZ"
    assert health.capabilities["search"] is True
    assert health.capabilities["lookup"] is True
    assert health.capabilities["financials"] is True
    assert health.requires_api_key is False
