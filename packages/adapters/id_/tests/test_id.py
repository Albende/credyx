"""Integration tests for the Indonesia adapter (AHU + OSS + IDX).

Integration tests hit real public endpoints (ahu.go.id, idx.co.id) — no
mocks, no fixtures. Pure-function tests cover identifier normalization.
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.id_ import IDAdapter
from packages.adapters.id_.adapter import (
    _format_npwp,
    _normalize_nib,
    _normalize_npwp,
    _parse_id_date,
)
from packages.shared.models import FilingType, IdentifierType


# Real test NPWPs from major Indonesian listed issuers.
BANK_MANDIRI_NPWP = "010604707073000"
TELKOM_NPWP = "010000131093000"
ASTRA_NPWP = "010000297091000"
UNILEVER_NPWP = "010017019433000"


def test_normalize_npwp_strips_formatting():
    assert _normalize_npwp("01.060.470.7-073.000") == BANK_MANDIRI_NPWP
    assert _normalize_npwp(" 010604707073000 ") == BANK_MANDIRI_NPWP
    assert _normalize_npwp("01-060-470-7-073-000") == BANK_MANDIRI_NPWP
    assert _normalize_npwp("ID010604707073000") == BANK_MANDIRI_NPWP


def test_normalize_npwp_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        _normalize_npwp("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_npwp("ABCDEFGHIJKLMNO")
    with pytest.raises(InvalidIdentifierError):
        _normalize_npwp("")
    with pytest.raises(InvalidIdentifierError):
        # 14 digits — too short.
        _normalize_npwp("01060470707300")


def test_format_npwp_roundtrips():
    formatted = _format_npwp(BANK_MANDIRI_NPWP)
    assert formatted == "01.060.470.7-073.000"
    assert _normalize_npwp(formatted) == BANK_MANDIRI_NPWP


def test_normalize_nib_strips_and_validates():
    assert _normalize_nib("1234567890123") == "1234567890123"
    assert _normalize_nib(" 1234567890123 ") == "1234567890123"
    with pytest.raises(InvalidIdentifierError):
        _normalize_nib("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nib("ABCDEFGHIJKLM")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nib("")


def test_parse_id_date_handles_iso_and_dmy():
    assert _parse_id_date("2010-04-19") == date(2010, 4, 19)
    assert _parse_id_date("19/04/2010") == date(2010, 4, 19)
    assert _parse_id_date("19-04-2010") == date(2010, 4, 19)
    assert _parse_id_date(None) is None
    assert _parse_id_date("not a date") is None


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = IDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Bank Mandiri")


@pytest.mark.asyncio
async def test_lookup_by_vat_raises_not_implemented():
    adapter = IDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, BANK_MANDIRI_NPWP)


@pytest.mark.asyncio
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = IDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "1234567890123"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier_type():
    adapter = IDAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, BANK_MANDIRI_NPWP)


@pytest.mark.asyncio
async def test_lookup_validates_npwp_shape_before_failing():
    adapter = IDAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-npwp")


@pytest.mark.asyncio
async def test_fetch_financials_rejects_garbage_id():
    adapter = IDAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-real-id")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_without_idx_hint():
    # Without an explicit IDX symbol hint there is no free path from
    # NPWP to ticker — the adapter MUST return [] rather than guess.
    adapter = IDAdapter()
    filings = await adapter.fetch_financials(BANK_MANDIRI_NPWP, years=3)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_with_idx_hint_for_listed_issuers():
    adapter = IDAdapter()
    # ``IDX:{ticker}`` is the documented opt-in hint for listed firms.
    for hint in ("IDX:BMRI", "IDX:TLKM", "IDX:ASII", "IDX:UNVR"):
        filings = await adapter.fetch_financials(hint, years=3)
        assert isinstance(filings, list)
        for f in filings:
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "IDR"
            assert f.document_url and f.document_url.startswith("https://")
            assert f.source_url and f.source_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = IDAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ID"
    # AHU search/lookup are 501 by design — health is either degraded
    # (portal reachable) or error (portal unreachable).
    assert health.status.value in ("degraded", "error")
    assert health.rate_limit_per_minute in (None, 30)
