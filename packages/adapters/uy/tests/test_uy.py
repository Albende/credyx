"""Integration + unit tests for the UY adapter.

Integration tests hit live free sources: the RUPE open-data registry on
``catalogodatos.gub.uy`` (search + lookup) and the BVM issuer document
pages on ``www.bvm.com.uy`` (financials). If a source is temporarily
unavailable the adapter raises `BlockedByRegistryError`; the integration
cases treat that as a skip — surfacing the block IS the contract under the
project's no-mock-data rule.

Test company: **PAMER S.A.** — RUT ``210000530018`` — present in RUPE and a
BVM-registered issuer that files *Estados Contables*, so all three
capabilities resolve for it.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    BlockedByRegistryError,
    InvalidIdentifierError,
)
from packages.adapters.uy import UYAdapter
from packages.adapters.uy.adapter import _norm_name, _normalize_rut
from packages.shared.models import FilingType, IdentifierType

PAMER_RUT = "210000530018"


def test_normalize_rut_accepts_common_formats():
    assert _normalize_rut("210000530018") == "210000530018"
    assert _normalize_rut("21.000.053.0018") == "210000530018"
    assert _normalize_rut("21-0000-5300-18") == "210000530018"
    assert _normalize_rut("  210000530018  ") == "210000530018"
    assert _normalize_rut("UY210000530018") == "210000530018"


def test_normalize_rut_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("1234567890123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("")


def test_normalize_rut_rejects_non_numeric():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("21000053001X")


def test_norm_name_collapses_legal_forms():
    assert _norm_name("PAMER S A") == _norm_name("Pamer S.A.")
    assert _norm_name("SAN ROQUE SOCIEDAD ANONIMA") == _norm_name("San Roque S.A.")


def test_adapter_class_metadata():
    adapter = UYAdapter()
    assert adapter.country_code == "UY"
    assert adapter.primary_identifier == IdentifierType.VAT
    assert IdentifierType.VAT in adapter.identifier_types
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_invalid_rut_rejected_before_http():
    adapter = UYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-rut")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = UYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, PAMER_RUT)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = UYAdapter()
    try:
        matches = await adapter.search_by_name("PAMER", limit=5)
    except BlockedByRegistryError:
        pytest.skip("RUPE datastore temporarily unavailable")
    assert matches
    assert any(m.id == PAMER_RUT for m in matches)
    assert all(m.country == "UY" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_pamer_via_rupe():
    adapter = UYAdapter()
    try:
        details = await adapter.lookup_by_identifier(IdentifierType.VAT, PAMER_RUT)
    except BlockedByRegistryError:
        pytest.skip("RUPE datastore temporarily unavailable")
    assert details is not None
    assert details.country == "UY"
    assert details.id == PAMER_RUT
    assert details.name
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_via_company_number_alias():
    adapter = UYAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, PAMER_RUT
        )
    except BlockedByRegistryError:
        pytest.skip("RUPE datastore temporarily unavailable")
    assert details is not None
    assert details.id == PAMER_RUT


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_real_bvm_pdfs():
    adapter = UYAdapter()
    try:
        filings = await adapter.fetch_financials(PAMER_RUT, years=3)
    except BlockedByRegistryError:
        pytest.skip("RUPE / BVM temporarily unavailable")
    assert filings
    for f in filings:
        assert f.company_id == PAMER_RUT
        assert f.type in {FilingType.BALANCE_SHEET, FilingType.ANNUAL_REPORT}
        assert f.document_format == "pdf"
        assert f.document_url and f.document_url.endswith(".pdf")
        assert "bvm.com.uy" in f.document_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_live_state():
    adapter = UYAdapter()
    health = await adapter.health_check()
    assert health.country_code == "UY"
    assert health.status.value in {"ok", "degraded", "error"}
