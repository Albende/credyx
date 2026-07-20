"""Integration + unit tests for the CL adapter.

Registry (name search + RUT lookup) is served from GLEIF; financials from
SEC EDGAR 20-F for US-cross-listed Chilean issuers. Integration tests hit
those live sources and MUST NOT pass on mocked responses.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.cl import CLAdapter
from packages.adapters.cl.adapter import (
    _format_rut,
    _normalize_rut,
    _rut_check_digit,
)
from packages.shared.models import FilingType, IdentifierType


def test_rut_check_digit_known_values():
    # Empresas COPEC: 90.690.000-9
    assert _rut_check_digit("90690000") == "9"
    # Banco de Chile: 97.004.000-5
    assert _rut_check_digit("97004000") == "5"
    # Falabella: 90.749.000-9
    assert _rut_check_digit("90749000") == "9"
    # LATAM Airlines Group: 89.862.200-2
    assert _rut_check_digit("89862200") == "2"


def test_rut_check_digit_k_and_zero_cases():
    # Mod-11 remainder 10 maps to "K"; remainder 11 maps to "0".
    assert _rut_check_digit("10000013") == "K"
    assert _rut_check_digit("10000004") == "0"


def test_normalize_rut_accepts_common_formats():
    assert _normalize_rut("90.690.000-9") == ("90690000", "9")
    assert _normalize_rut("90690000-9") == ("90690000", "9")
    assert _normalize_rut("CL90690000-9") == ("90690000", "9")
    assert _normalize_rut("  90690000-9  ") == ("90690000", "9")


def test_normalize_rut_rejects_bad_check():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("90690000-1")


def test_normalize_rut_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("not-a-rut")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("123-4")


def test_format_rut_inserts_separators():
    assert _format_rut("90690000", "9") == "90.690.000-9"
    assert _format_rut("89862200", "2") == "89.862.200-2"


@pytest.mark.asyncio
async def test_invalid_rut_rejected_before_http():
    adapter = CLAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345678-9")


@pytest.mark.asyncio
async def test_wrong_identifier_type_rejected():
    adapter = CLAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "97.004.000-5")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_gleif():
    adapter = CLAdapter()
    matches = await adapter.search_by_name("Banco de Chile", limit=5)
    assert matches
    top = matches[0]
    assert top.country == "CL"
    assert "chile" in top.name.lower()
    assert any(i.type == IdentifierType.VAT for i in top.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banco_de_chile_gleif():
    adapter = CLAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "97.004.000-5"
    )
    assert details is not None
    assert details.country == "CL"
    assert "banco de chile" in details.name.lower()
    assert details.id == "97.004.000-5"
    assert any(i.type == IdentifierType.LEI for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_banco_de_chile_edgar():
    adapter = CLAdapter()
    filings = await adapter.fetch_financials("97.004.000-5", years=3)
    assert filings
    for f in filings:
        assert f.company_id == "97.004.000-5"
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "CLP"
        assert f.document_url and "sec.gov/Archives" in f.document_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_live_state():
    adapter = CLAdapter()
    health = await adapter.health_check()
    assert health.country_code == "CL"
    assert health.status.value in {"ok", "degraded", "error"}
