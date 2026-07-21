from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.do import DOAdapter
from packages.adapters.do.adapter import _classify, _extract_period, _normalize_rnc
from packages.shared.models import FilingType, IdentifierType

# Real DGII-registered RNCs (verified against the DGII_RNC master roster).
BANCO_POPULAR = "101010632"  # Banco Popular Dominicano — BVRD-listed
CERVECERIA = "101003723"  # Cervecería Nacional Dominicana — not BVRD-listed


def test_normalize_rnc_strips_separators():
    assert _normalize_rnc("1-01.010 632") == "101010632"
    assert _normalize_rnc("101010632") == "101010632"


def test_normalize_rnc_accepts_11_digits():
    assert _normalize_rnc("00112345678") == "00112345678"


def test_normalize_rnc_rejects_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rnc("12345")


def test_normalize_rnc_rejects_letters():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rnc("ABC123456")


def test_classify_maps_statement_types():
    assert _classify("BCO POPULAR Balance General.pdf") == FilingType.BALANCE_SHEET
    assert _classify("Estado de Resultados.pdf") == FilingType.PROFIT_AND_LOSS
    assert _classify("Flujo de Efectivo.pdf") == FilingType.CASH_FLOW
    assert _classify("EEFF Auditados 2023.pdf") == FilingType.AUDIT_REPORT


def test_extract_period_reads_month_and_year():
    year, period_end = _extract_period("EEFFS Trimestrales Sep 2020.pdf", "")
    assert year == 2020
    assert period_end is not None and period_end.month == 9


@pytest.mark.asyncio
async def test_search_requires_min_length():
    adapter = DOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.search_by_name("abc", limit=5)


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = DOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, BANCO_POPULAR)


@pytest.mark.asyncio
async def test_fetch_financials_validates_rnc():
    adapter = DOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-rnc")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_dgii():
    adapter = DOAdapter()
    health = await adapter.health_check()
    assert health.country_code == "DO"
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_cerveceria():
    adapter = DOAdapter()
    results = await adapter.search_by_name("CERVECERIA NACIONAL", limit=5)
    assert results
    assert any("CERVECERIA" in m.name.upper() for m in results)
    assert all(m.country == "DO" and m.id.isdigit() for m in results)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banco_popular_rnc():
    adapter = DOAdapter()
    result = await adapter.lookup_by_identifier(IdentifierType.VAT, BANCO_POPULAR)
    assert result is not None
    assert result.id == BANCO_POPULAR
    assert "BANCO POPULAR" in result.name.upper()
    assert result.status == "ACTIVO"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_banco_popular_returns_filings():
    adapter = DOAdapter()
    filings = await adapter.fetch_financials(BANCO_POPULAR, years=3)
    assert filings
    assert all(f.company_id == BANCO_POPULAR for f in filings)
    assert all(f.year >= 2000 for f in filings)
