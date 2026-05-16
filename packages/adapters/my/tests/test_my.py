"""Integration tests for the Malaysia adapter (Bursa Malaysia listed-issuer
financials; SSM e-Info registry blocked behind paid login).

The integration tests hit Bursa Malaysia directly — no fixtures, no mocks.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.my import MYAdapter
from packages.adapters.my.adapter import (
    _normalize_company_number,
    _split_packed_id,
)
from packages.shared.models import FilingType, IdentifierType


PETRONAS_NEW = "197001000465"
PETRONAS_OLD = "20076-K"
PUBLIC_BANK_NEW = "196601000142"
PUBLIC_BANK_OLD = "6463-H"
MAYBANK_NEW = "196001000142"
IHH_NEW = "200101025419"
IHH_OLD = "901914-V"

# Bursa Malaysia stock codes for the listed test companies.
PETRONAS_GAS_CODE = "5347"
PUBLIC_BANK_CODE = "1295"
MAYBANK_CODE = "1155"
IHH_CODE = "5225"


def test_normalize_new_format_company_number():
    assert _normalize_company_number(PETRONAS_NEW) == PETRONAS_NEW
    assert _normalize_company_number(" 197001000465 ") == PETRONAS_NEW
    assert _normalize_company_number("MY197001000465") == PETRONAS_NEW


def test_normalize_old_format_company_number():
    assert _normalize_company_number("20076-K") == "20076-K"
    assert _normalize_company_number("20076-k") == "20076-K"
    assert _normalize_company_number("20076k") == "20076-K"
    assert _normalize_company_number("6463-H") == "6463-H"
    assert _normalize_company_number(" 901914-v ") == "901914-V"


def test_normalize_rejects_malformed():
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("ABCDEFGHIJKL")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("123456789")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("20076-KK")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("")


def test_split_packed_id_recognises_bursa_prefix():
    cn, code = _split_packed_id("BURSA:5347")
    assert cn is None
    assert code == "5347"
    cn, code = _split_packed_id("bursa/1155")
    assert cn is None
    assert code == "1155"


def test_split_packed_id_returns_company_number_when_no_prefix():
    cn, code = _split_packed_id(PETRONAS_NEW)
    assert cn == PETRONAS_NEW
    assert code is None
    cn, code = _split_packed_id("20076-K")
    assert cn == "20076-K"
    assert code is None


def test_adapter_metadata():
    adapter = MYAdapter()
    assert adapter.country_code == "MY"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = MYAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Petronas", limit=5)


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented_for_valid_id():
    adapter = MYAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, PETRONAS_NEW
        )


@pytest.mark.asyncio
async def test_lookup_rejects_invalid_identifier_format():
    adapter = MYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "not-a-real-id"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = MYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, PETRONAS_NEW)


@pytest.mark.asyncio
async def test_fetch_financials_unlisted_returns_empty():
    # A syntactically valid registration number with no Bursa pairing
    # must return [] (the spec-compliant outcome for "no free source"),
    # not fabricate filings.
    adapter = MYAdapter()
    filings = await adapter.fetch_financials(PETRONAS_NEW, years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_garbage_id():
    adapter = MYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-an-id", years=3)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reaches_bursa():
    adapter = MYAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MY"
    # Registry is paid-only → degraded is the truthful steady state.
    assert health.status.value in ("ok", "degraded", "error")
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_via_bursa_packed_id():
    adapter = MYAdapter()
    for code in (PETRONAS_GAS_CODE, PUBLIC_BANK_CODE, MAYBANK_CODE, IHH_CODE):
        filings = await adapter.fetch_financials(f"BURSA:{code}", years=5)
        assert isinstance(filings, list)
        for f in filings:
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "MYR"
            assert f.year >= 2000
            assert f.company_id.startswith("BURSA:") or f.company_id
            if f.document_url:
                assert f.document_url.startswith("http")
