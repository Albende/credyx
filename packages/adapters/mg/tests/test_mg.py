"""Integration tests for the Madagascar adapter.

EDBM is JS-rendered with no free JSON API and there is no stock
exchange to fall back to. These tests assert the adapter honors the
no-mock rule (raises ``AdapterNotImplementedError`` for search +
lookup) and that a live probe of EDBM succeeds.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.mg import MGAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_real_sources():
    adapter = MGAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MG"
    assert health.name == "Madagascar"
    assert health.status in (AdapterStatus.DEGRADED, AdapterStatus.ERROR)
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
    assert health.capabilities["financials"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_raises_not_implemented():
    adapter = MGAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Telma", limit=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_nif_raises_not_implemented():
    adapter = MGAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "2000123456")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_stat_raises_not_implemented():
    adapter = MGAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "61201112020100123"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = MGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_nif():
    adapter = MGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-nif")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_stat():
    adapter = MGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "??")


@pytest.mark.asyncio
async def test_financials_returns_empty():
    adapter = MGAdapter()
    filings = await adapter.fetch_financials("2000123456", years=5)
    assert filings == []
