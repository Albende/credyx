"""Integration + unit tests for the UY adapter.

Integration tests hit DGI's public RUT consultation service directly. If
the service returns a non-JSON body (intermittent maintenance / HTML
fallback) the adapter raises `BlockedByRegistryError`; the integration
cases treat that as a skip — surfacing the block IS the contract under
the project's no-mock-data rule.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    BlockedByRegistryError,
    InvalidIdentifierError,
)
from packages.adapters.uy import UYAdapter
from packages.adapters.uy.adapter import _normalize_rut
from packages.shared.models import FilingType, IdentifierType


def test_normalize_rut_accepts_common_formats():
    assert _normalize_rut("215521240017") == "215521240017"
    assert _normalize_rut("21.552.124.0017") == "215521240017"
    assert _normalize_rut("21-5521-2400-17") == "215521240017"
    assert _normalize_rut("  215521240017  ") == "215521240017"
    assert _normalize_rut("UY215521240017") == "215521240017"


def test_normalize_rut_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("1234567890123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("")


def test_normalize_rut_rejects_non_numeric():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rut("21552124001X")


def test_adapter_class_metadata():
    adapter = UYAdapter()
    assert adapter.country_code == "UY"
    assert adapter.primary_identifier == IdentifierType.VAT
    assert IdentifierType.VAT in adapter.identifier_types
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = UYAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("ANCAP")


@pytest.mark.asyncio
async def test_invalid_rut_rejected_before_http():
    adapter = UYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-rut")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = UYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "215521240017")


@pytest.mark.asyncio
async def test_fetch_financials_returns_bvm_pointers():
    adapter = UYAdapter()
    filings = await adapter.fetch_financials("215521240017", years=3)
    assert len(filings) == 3
    for f in filings:
        assert f.company_id == "215521240017"
        assert f.currency == "UYU"
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.document_url and "bvm.com.uy" in f.document_url
        assert f.document_format == "html"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_live_state():
    adapter = UYAdapter()
    health = await adapter.health_check()
    assert health.country_code == "UY"
    assert health.status.value in {"ok", "degraded", "error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ancap_dgi():
    adapter = UYAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.VAT, "215521240017"
        )
    except BlockedByRegistryError:
        pytest.skip("DGI consultation temporarily unavailable")
    if details is None:
        pytest.skip("DGI returned no payload for ANCAP RUT")
    assert details.country == "UY"
    assert details.id == "215521240017"
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)
    assert details.name  # registry must surface a non-empty name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_antel_via_company_number_alias():
    adapter = UYAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "215521280011"
        )
    except BlockedByRegistryError:
        pytest.skip("DGI consultation temporarily unavailable")
    if details is None:
        pytest.skip("DGI returned no payload for ANTEL RUT")
    assert details.country == "UY"
    assert details.id == "215521280011"
