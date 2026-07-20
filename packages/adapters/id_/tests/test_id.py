"""Integration tests for the Indonesia adapter (IDX).

Integration tests hit the real IDX public endpoints (idx.co.id) via the
FlareSolverr bot-bypass path — no mocks, no fixtures. Pure-function tests
cover identifier normalization.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.id_ import IDAdapter
from packages.adapters.id_.adapter import (
    _extract_json,
    _format_npwp,
    _norm_ticker,
    _normalize_npwp,
)
from packages.shared.models import FilingType, IdentifierType


# Real test NPWPs from major Indonesian listed issuers, as published by IDX.
BANK_MANDIRI_NPWP = "010611739093000"
TELKOM_NPWP = "010000131093000"
ASTRA_NPWP = "013025846092000"
UNILEVER_NPWP = "010017010092000"


def test_normalize_npwp_strips_formatting():
    assert _normalize_npwp("01.061.173.9-093.000") == BANK_MANDIRI_NPWP
    assert _normalize_npwp(" 010611739093000 ") == BANK_MANDIRI_NPWP
    assert _normalize_npwp("ID010611739093000") == BANK_MANDIRI_NPWP


def test_normalize_npwp_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        _normalize_npwp("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_npwp("ABCDEFGHIJKLMNO")
    with pytest.raises(InvalidIdentifierError):
        _normalize_npwp("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_npwp("01060470707300")  # 14 digits — too short.


def test_format_npwp_roundtrips():
    formatted = _format_npwp(TELKOM_NPWP)
    assert formatted == "01.000.013.1-093.000"
    assert _normalize_npwp(formatted) == TELKOM_NPWP


def test_norm_ticker_accepts_plain_and_hinted():
    assert _norm_ticker("bmri") == "BMRI"
    assert _norm_ticker(" TLKM ") == "TLKM"
    assert _norm_ticker("IDX:asii") == "ASII"
    assert _norm_ticker("012345") is None
    assert _norm_ticker("TOOLONG") is None


def test_extract_json_handles_flaresolverr_wrapper():
    raw = '{"a": 1, "b": "x & y"}'
    assert _extract_json(raw) == {"a": 1, "b": "x & y"}
    wrapped = "<html><body><pre>{&quot;a&quot;: 1, &quot;b&quot;: &quot;x &amp; y&quot;}</pre></body></html>"
    assert _extract_json(wrapped) == {"a": 1, "b": "x & y"}


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
        await adapter.fetch_financials("not-a-real-id!!")


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty():
    adapter = IDAdapter()
    assert await adapter.search_by_name("") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_listed_issuer():
    adapter = IDAdapter()
    results = await adapter.search_by_name("Bank Mandiri", limit=5)
    assert results
    top = results[0]
    assert top.id == "BMRI"
    assert "Mandiri" in top.name
    assert any(i.type == IdentifierType.VAT for i in top.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_npwp_returns_details():
    adapter = IDAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, TELKOM_NPWP)
    assert details is not None
    assert details.id == "TLKM"
    assert details.country == "ID"
    assert details.registered_address


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_ticker_returns_details():
    adapter = IDAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.OTHER, "IDX:ASII")
    assert details is not None
    assert details.id == "ASII"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_real_filings():
    adapter = IDAdapter()
    for hint in ("TLKM", "IDX:BMRI", ASTRA_NPWP):
        filings = await adapter.fetch_financials(hint, years=3)
        assert filings, f"expected filings for {hint}"
        for f in filings:
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "IDR"
            assert f.document_format == "pdf"
            assert f.document_url and f.document_url.startswith("https://www.idx.co.id/")
            assert f.source_url and f.source_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = IDAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ID"
    assert health.status.value in ("ok", "degraded", "error")
    assert health.rate_limit_per_minute in (None, 30)
