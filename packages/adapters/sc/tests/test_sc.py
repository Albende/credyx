from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.sc import SCAdapter
from packages.adapters.sc.adapter import _normalize_company_number
from packages.shared.models import AdapterStatus, IdentifierType


def test_company_number_normalizer_accepts_alnum():
    assert _normalize_company_number("123456") == "123456"
    assert _normalize_company_number("abc 123") == "ABC123"
    assert _normalize_company_number("8901234-1") == "89012341"


def test_company_number_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("abc")  # below 4 chars after normalization
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("not/a/valid#id")


def test_adapter_metadata():
    adapter = SCAdapter()
    assert adapter.country_code == "SC"
    assert adapter.country_name == "Seychelles"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert adapter.identifier_types == [IdentifierType.COMPANY_NUMBER]
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = SCAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Anything Ltd")


@pytest.mark.asyncio
async def test_lookup_by_identifier_raises_not_implemented():
    adapter = SCAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "123456"
        )


@pytest.mark.asyncio
async def test_fetch_financials_unknown_returns_empty():
    adapter = SCAdapter()
    assert await adapter.fetch_financials("999999") == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_identifier():
    adapter = SCAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("!!")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_merj():
    adapter = SCAdapter()
    health = await adapter.health_check()
    assert health.country_code == "SC"
    # MERJ is the only free SC source; search/lookup are intentionally off
    # because the FSA registry is paywalled.
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
    assert health.capabilities["financials"] is True
    # Either DEGRADED (reachable but no public registry) or ERROR (probe
    # failed) are both honest answers — we never report OK because we
    # cannot search or lookup.
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.ERROR}
