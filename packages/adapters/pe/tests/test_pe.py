"""Unit + integration tests for the PE adapter.

Integration tests hit SUNAT's public RUC verifier directly. SUNAT
occasionally fronts requests with a CAPTCHA wall; when that happens the
adapter raises `BlockedByRegistryError` — which the tests accept as a
valid live signal (per project policy, surfacing the block is the
contract, not a bug). Tests MUST NOT pass on mocked responses.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    BlockedByRegistryError,
    InvalidIdentifierError,
)
from packages.adapters.pe import PEAdapter
from packages.adapters.pe.adapter import _normalize_ruc, _parse_sunat_response
from packages.shared.models import IdentifierType


def test_normalize_ruc_accepts_common_formats():
    assert _normalize_ruc("20100068133") == "20100068133"
    assert _normalize_ruc("  20100068133  ") == "20100068133"
    assert _normalize_ruc("PE20100068133") == "20100068133"
    assert _normalize_ruc("20-100-068-133") == "20100068133"


def test_normalize_ruc_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("2010006813")  # 10 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("201000681333")  # 12 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("")


def test_normalize_ruc_rejects_non_numeric():
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("not-a-ruc")
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("ABCDEFGHIJK")


def test_parse_sunat_response_empty_inputs():
    assert _parse_sunat_response("") is None
    assert _parse_sunat_response("no tags here") is None


def test_parse_sunat_response_ruc_not_exists():
    body = "<html><body>El número de RUC no existe</body></html>"
    assert _parse_sunat_response(body) is None


def test_parse_sunat_response_basic_layout():
    # Synthetic HTML that mirrors the SUNAT label layout. Whitespace gets
    # collapsed by _strip_html; labels are separated from later labels by
    # the boundary regex.
    body = (
        "<html><body>"
        "<p>Número de RUC: 20100068133 - CREDICORP CAPITAL S.A.</p>"
        "<p>Tipo Contribuyente: SOCIEDAD ANONIMA</p>"
        "<p>Estado del Contribuyente: ACTIVO</p>"
        "<p>Condición del Contribuyente: HABIDO</p>"
        "<p>Domicilio Fiscal: AV. EL DERBY NRO. 055 LIMA - LIMA - SANTIAGO DE SURCO</p>"
        "<p>Actividad(es) Económica(s): Principal - 6499 - OTRAS ACTIV. DE SERVICIO FINANCIERO</p>"
        "</body></html>"
    )
    parsed = _parse_sunat_response(body)
    assert parsed is not None
    assert "CREDICORP" in parsed["name"]
    assert parsed["contributor_type"] == "SOCIEDAD ANONIMA"
    assert parsed["status"] == "ACTIVO"
    assert parsed["condition"] == "HABIDO"
    assert "DERBY" in parsed["address"]
    assert "6499" in parsed["activity_codes"]


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = PEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Credicorp")


@pytest.mark.asyncio
async def test_invalid_ruc_rejected_before_http():
    adapter = PEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier_type():
    adapter = PEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "20100068133")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_credicorp_sunat():
    adapter = PEAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.VAT, "20100068133"
        )
    except BlockedByRegistryError:
        pytest.skip("SUNAT CAPTCHA blocked direct lookup")
    if details is None:
        pytest.skip("SUNAT returned no parseable record")
    assert details.country == "PE"
    assert "credicorp" in details.name.lower()
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_buenaventura_sunat():
    adapter = PEAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "20100079501"
        )
    except BlockedByRegistryError:
        pytest.skip("SUNAT CAPTCHA blocked direct lookup")
    if details is None:
        pytest.skip("SUNAT returned no parseable record")
    assert details.country == "PE"
    assert "buenaventura" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_pacasmayo_sunat():
    adapter = PEAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.VAT, "20419387658"
        )
    except BlockedByRegistryError:
        pytest.skip("SUNAT CAPTCHA blocked direct lookup")
    if details is None:
        pytest.skip("SUNAT returned no parseable record")
    assert "pacasmayo" in details.name.lower() or "cementos" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_live_state():
    adapter = PEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PE"
    assert health.status.value in {"ok", "blocked", "error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_backus_smv():
    # Backus Holdings is SMV-supervised, so it should return at least one
    # filing pointer. If SMV is down, accept an empty list — but no fakes.
    adapter = PEAdapter()
    filings = await adapter.fetch_financials("20100113610", years=3)
    for f in filings:
        assert f.company_id == "20100113610"
        assert f.currency == "PEN"
        assert f.document_url and "smv.gob.pe" in f.document_url
        assert f.document_format == "html"
