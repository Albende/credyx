"""Integration + unit tests for the CL adapter.

The integration tests hit SII directly. SII enforces a CAPTCHA on the
public RUT verifier, so the integration cases accept either a parsed
`CompanyDetails` or a `BlockedByRegistryError` — both are valid signals
of a live source. They MUST NOT pass on a mocked response.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    BlockedByRegistryError,
    InvalidIdentifierError,
)
from packages.adapters.cl import CLAdapter
from packages.adapters.cl.adapter import (
    _format_rut,
    _normalize_rut,
    _rut_check_digit,
)
from packages.shared.models import IdentifierType


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
async def test_search_by_name_raises_not_implemented():
    adapter = CLAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Copec")


@pytest.mark.asyncio
async def test_invalid_rut_rejected_before_http():
    adapter = CLAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345678-9")


@pytest.mark.asyncio
async def test_fetch_financials_returns_cmf_pointers():
    adapter = CLAdapter()
    filings = await adapter.fetch_financials("90.690.000-9", years=3)
    assert len(filings) == 3
    for f in filings:
        assert f.company_id == "90.690.000-9"
        assert f.currency == "CLP"
        assert f.document_url and "cmfchile.cl" in f.document_url
        assert f.document_format == "html"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_copec_sii():
    adapter = CLAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.VAT, "90.690.000-9"
        )
    except BlockedByRegistryError:
        # SII CAPTCHA wall — surfacing the block is the contract, not a bug.
        pytest.skip("SII CAPTCHA blocked direct lookup")
    assert details is not None
    assert details.country == "CL"
    assert "copec" in details.name.lower()
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banco_de_chile_sii():
    adapter = CLAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "97004000-5"
        )
    except BlockedByRegistryError:
        pytest.skip("SII CAPTCHA blocked direct lookup")
    assert details is not None
    assert "banco" in details.name.lower() or "chile" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_live_state():
    adapter = CLAdapter()
    health = await adapter.health_check()
    assert health.country_code == "CL"
    assert health.status.value in {"ok", "blocked", "error"}
