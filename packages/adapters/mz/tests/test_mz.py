from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.mz import MZAdapter
from packages.adapters.mz.adapter import _normalize_nuit
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


def test_nuit_normalizer_accepts_nine_digits():
    assert _normalize_nuit("400123456") == "400123456"
    assert _normalize_nuit(" 400 123 456 ") == "400123456"
    assert _normalize_nuit("400-123-456") == "400123456"


def test_nuit_normalizer_rejects_bad_input():
    with pytest.raises(InvalidIdentifierError):
        _normalize_nuit("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nuit("40012345A")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nuit("4001234567")


def test_adapter_metadata():
    a = MZAdapter()
    assert a.country_code == "MZ"
    assert a.country_name == "Mozambique"
    assert IdentifierType.VAT in a.identifier_types
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert a.primary_identifier == IdentifierType.VAT
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    a = MZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.search_by_name("Cervejas")


@pytest.mark.asyncio
async def test_lookup_validates_nuit_format_before_raising():
    a = MZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await a.lookup_by_identifier(IdentifierType.VAT, "abc")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier_type():
    a = MZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await a.lookup_by_identifier(IdentifierType.LEI, "529900T8BM49AURSDO55")


@pytest.mark.asyncio
async def test_lookup_with_valid_nuit_raises_not_implemented():
    a = MZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.lookup_by_identifier(IdentifierType.VAT, "400123456")


@pytest.mark.asyncio
async def test_fetch_financials_unknown_returns_empty():
    a = MZAdapter()
    assert await a.fetch_financials("UNKNOWN-TICKER") == []


@pytest.mark.asyncio
async def test_fetch_financials_bvm_listed_returns_pointer():
    a = MZAdapter()
    filings = await a.fetch_financials("CDM")
    assert len(filings) == 1
    f = filings[0]
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "MZN"
    assert f.structured_data is None
    assert f.source_url and "bvm.co.mz" in f.source_url


@pytest.mark.asyncio
async def test_fetch_financials_hcb_listed():
    a = MZAdapter()
    filings = await a.fetch_financials("HCB")
    assert len(filings) == 1
    assert "bvm.co.mz" in (filings[0].source_url or "")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_bvm():
    a = MZAdapter()
    h = await a.health_check()
    assert h.country_code == "MZ"
    assert h.status in (
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    )
    assert h.rate_limit_per_minute == 30
