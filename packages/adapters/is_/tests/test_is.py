"""Integration tests for the Iceland adapter (Skatturinn + Nasdaq Iceland).

Integration tests hit real public endpoints (skatturinn.is,
nasdaqomxnordic.com) — no mocks, no fixtures. Pure-function tests cover
identifier normalization.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.is_ import ISAdapter
from packages.adapters.is_.adapter import (
    _format_kennitala,
    _normalize_kennitala,
)
from packages.shared.models import FilingType, IdentifierType


# Real Icelandic kennitalas from major listed issuers.
MAREL_KT = "6204830369"
ARION_KT = "5810080150"
ICELANDAIR_KT = "6312051780"
SIMINN_KT = "4602070810"


def test_normalize_kennitala_strips_formatting():
    assert _normalize_kennitala("620483-0369") == MAREL_KT
    assert _normalize_kennitala(" 6204830369 ") == MAREL_KT
    assert _normalize_kennitala("IS6204830369") == MAREL_KT
    assert _normalize_kennitala("620483 0369") == MAREL_KT


def test_normalize_kennitala_rejects_invalid():
    with pytest.raises(InvalidIdentifierError):
        _normalize_kennitala("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_kennitala("ABCDEFGHIJ")
    with pytest.raises(InvalidIdentifierError):
        _normalize_kennitala("")
    with pytest.raises(InvalidIdentifierError):
        # 9 digits — too short.
        _normalize_kennitala("620483036")
    with pytest.raises(InvalidIdentifierError):
        # 11 digits — too long.
        _normalize_kennitala("62048303691")


def test_format_kennitala_roundtrips():
    formatted = _format_kennitala(MAREL_KT)
    assert formatted == "620483-0369"
    assert _normalize_kennitala(formatted) == MAREL_KT


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = ISAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Marel")


@pytest.mark.asyncio
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = ISAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, MAREL_KT)


@pytest.mark.asyncio
async def test_lookup_by_vat_raises_not_implemented():
    adapter = ISAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, ARION_KT)


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier_type():
    adapter = ISAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, MAREL_KT)


@pytest.mark.asyncio
async def test_lookup_validates_kennitala_shape_before_failing():
    adapter = ISAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "not-a-kennitala"
        )


@pytest.mark.asyncio
async def test_fetch_financials_rejects_garbage_id():
    adapter = ISAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-real-id")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_without_nasdaq_hint():
    # A bare kennitala has no free path to a Nasdaq ticker — the adapter
    # MUST return [] rather than invent filings.
    adapter = ISAdapter()
    filings = await adapter.fetch_financials(MAREL_KT, years=3)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_with_nasdaq_hint_for_listed_issuers():
    adapter = ISAdapter()
    # ``NASDAQ:{ticker}`` is the documented opt-in hint for listed firms.
    for hint in ("NASDAQ:ARION", "NASDAQ:ICEAIR", "NASDAQ:SIMINN"):
        filings = await adapter.fetch_financials(hint, years=3)
        assert isinstance(filings, list)
        for f in filings:
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "ISK"
            assert f.document_url and f.document_url.startswith("https://")
            assert f.source_url and f.source_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = ISAdapter()
    health = await adapter.health_check()
    assert health.country_code == "IS"
    # Skatturinn search/lookup are 501 by design — health is either
    # degraded (portal reachable) or error (portal unreachable).
    assert health.status.value in ("degraded", "error")
    assert health.rate_limit_per_minute in (None, 30)
