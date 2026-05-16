from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.uz import UZAdapter
from packages.adapters.uz.adapter import _normalize_inn
from packages.shared.models import IdentifierType


def test_normalize_inn_strips_prefix_and_whitespace():
    assert _normalize_inn("207056720") == "207056720"
    assert _normalize_inn(" 207056720 ") == "207056720"
    assert _normalize_inn("UZ207056720") == "207056720"
    assert _normalize_inn("uz 207056720") == "207056720"
    assert _normalize_inn("207-056-720") == "207056720"


def test_normalize_inn_rejects_invalid_lengths():
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("2070567200")  # 10 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("20705672A")


@pytest.mark.asyncio
async def test_search_by_name_not_implemented():
    adapter = UZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Uzbekneftegaz")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = UZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "207056720"
        )


@pytest.mark.asyncio
async def test_lookup_validates_inn_shape_before_failing():
    adapter = UZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "not-an-inn"
        )


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented_for_valid_inn():
    adapter = UZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "207056720"
        )


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_valid_inn():
    adapter = UZAdapter()
    # Hamkorbank-style 9-digit INN — no mock data, just an honest empty list.
    assert await adapter.fetch_financials("207056720") == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_id():
    adapter = UZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("garbage")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = UZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "UZ"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30
    # Either DEGRADED (UZSE reachable but no structured endpoint) or
    # ERROR (probe failed) — we never claim OK because lookup/search
    # are not implemented.
    assert health.status.value in {"degraded", "error"}
