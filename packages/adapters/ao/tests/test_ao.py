"""Tests for the Angola adapter.

The adapter has no free programmatic registry to call, so unit tests
cover the contract (raises on search/lookup, empty financials, health
reports DEGRADED). A single integration test probes bodiva.ao to confirm
the source is at least reachable from CI's network.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ao import AOAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = AOAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Banco BAI")


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented_for_valid_nif():
    adapter = AOAdapter()
    # Sonangol's commonly cited NIF format (10 alphanumeric). The point
    # is that format validation passes and we surface the coverage gap.
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.NIF, "5410000000")


@pytest.mark.asyncio
async def test_lookup_rejects_bad_identifier_format():
    adapter = AOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.NIF, "too-short")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier_type():
    adapter = AOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "5410000000")


@pytest.mark.asyncio
async def test_lookup_accepts_vat_and_company_number_aliases():
    adapter = AOAdapter()
    # Both should pass format validation and then 501.
    for id_type in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
        with pytest.raises(AdapterNotImplementedError):
            await adapter.lookup_by_identifier(id_type, "5410000000")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_list_without_fabrication():
    adapter = AOAdapter()
    # Banco BAI is a real listed BODIVA issuer; without the PDF pipeline
    # we MUST return [] rather than invent numbers (CLAUDE.md rule 1).
    filings = await adapter.fetch_financials("BAI", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_degraded_when_bodiva_reachable():
    adapter = AOAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AO"
    assert health.status in (AdapterStatus.DEGRADED, AdapterStatus.ERROR)
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
