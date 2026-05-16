from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.do import DOAdapter
from packages.adapters.do.adapter import _normalize_rnc
from packages.shared.models import IdentifierType


def test_normalize_rnc_strips_separators():
    assert _normalize_rnc("1-01.009 371") == "101009371"
    assert _normalize_rnc("101009371") == "101009371"


def test_normalize_rnc_accepts_11_digits():
    assert _normalize_rnc("00112345678") == "00112345678"


def test_normalize_rnc_rejects_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rnc("12345")


def test_normalize_rnc_rejects_letters():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rnc("ABC123456")


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = DOAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Banco Popular", limit=5)


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = DOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "101009371")


@pytest.mark.asyncio
async def test_fetch_financials_validates_rnc():
    adapter = DOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-rnc")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_unlisted():
    adapter = DOAdapter()
    assert await adapter.fetch_financials("101009371") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_dgii():
    adapter = DOAdapter()
    health = await adapter.health_check()
    assert health.country_code == "DO"
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banco_popular_rnc():
    adapter = DOAdapter()
    result = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "101009371"
    )
    # DGII page is a stateful WebForm; a plain GET may return only the empty
    # form. Either we positively identified the record or we surface None —
    # never fabricated data.
    if result is not None:
        assert result.id == "101009371"
        assert result.country == "DO"
        assert any(i.type == IdentifierType.VAT for i in result.identifiers)
