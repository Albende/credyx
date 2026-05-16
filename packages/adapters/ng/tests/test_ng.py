from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ng import NGAdapter
from packages.adapters.ng.adapter import _normalize_rc, _normalize_tin
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_rc_strips_prefix_and_spaces():
    assert _normalize_rc("RC208767") == "208767"
    assert _normalize_rc("rc 208767") == "208767"
    assert _normalize_rc(" 208767 ") == "208767"
    assert _normalize_rc("RC-1241300") == "1241300"


def test_normalize_rc_rejects_non_numeric():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rc("RC-ABCDE")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rc("")


def test_normalize_tin_accepts_8_to_14_digits():
    assert _normalize_tin("0123456789") == "0123456789"
    assert _normalize_tin("12345678") == "12345678"
    assert _normalize_tin("12345678901234") == "12345678901234"


def test_normalize_tin_rejects_bad_format():
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("ABCDEFGH")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_cac():
    adapter = NGAdapter()
    health = await adapter.health_check()
    assert health.country_code == "NG"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
    assert health.capabilities["financials"] is True


@pytest.mark.asyncio
async def test_lookup_invalid_rc_format_raises():
    adapter = NGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "RC-XYZ")


@pytest.mark.asyncio
async def test_lookup_invalid_tin_format_raises():
    adapter = NGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12")


@pytest.mark.asyncio
async def test_lookup_unsupported_identifier_raises():
    adapter = NGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_search_too_short_raises():
    adapter = NGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.search_by_name("D", limit=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_dangote_best_effort():
    """CAC search is JS-rendered; we accept real matches or 501."""
    adapter = NGAdapter()
    try:
        results = await adapter.search_by_name("Dangote Cement", limit=5)
    except AdapterNotImplementedError:
        return
    assert isinstance(results, list)
    for r in results:
        assert r.country == "NG"
        assert r.identifiers


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_dangote_cement_rc_best_effort():
    """Dangote Cement Plc — RC 208767.

    CAC public details are session-gated. Accept a real match or a 501.
    """
    adapter = NGAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "RC208767"
        )
    except AdapterNotImplementedError:
        return
    if details is None:
        return
    assert details.country == "NG"
    assert details.id == "208767"
    assert any(i.value == "208767" for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_mtn_rc_best_effort():
    """MTN Nigeria — RC 1241300."""
    adapter = NGAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "1241300"
        )
    except AdapterNotImplementedError:
        return
    if details is None:
        return
    assert details.country == "NG"
    assert details.id == "1241300"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_unlisted_returns_empty():
    """No free RC→NGX ticker resolver; expect [] not 501."""
    adapter = NGAdapter()
    filings = await adapter.fetch_financials("RC613", years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_id():
    adapter = NGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("BAD-ID", years=3)
