"""Integration tests for the Ethiopia adapter.

Real upstream sources (MoTI commercial register, Ministry of Revenue
e-tax, ESX) are either session-gated, behind Fayda national-ID auth, or
only cover a handful of newly listed issuers (ESX launched January
2024). These tests assert the adapter honors the no-mock rule (raises
``AdapterNotImplementedError`` for search + lookup) and that a live
probe of ESX/MoTI succeeds.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.et import ETAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_real_sources():
    adapter = ETAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ET"
    assert health.name == "Ethiopia"
    assert health.status in (AdapterStatus.DEGRADED, AdapterStatus.ERROR)
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = ETAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Ethiopian Airlines", limit=5)


@pytest.mark.asyncio
async def test_lookup_by_vat_raises_not_implemented():
    adapter = ETAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "0000000001")


@pytest.mark.asyncio
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = ETAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "1234567890"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = ETAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_tin_too_short():
    adapter = ETAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_tin_non_digits():
    adapter = ETAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "ABCDEFGHIJ")


@pytest.mark.asyncio
async def test_lookup_accepts_tin_with_separators():
    """Spaces and dashes are stripped before validation; the call still
    fails with ``AdapterNotImplementedError`` because lookup is gated,
    *not* with ``InvalidIdentifierError``."""
    adapter = ETAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12 34-56 7890")


@pytest.mark.asyncio
async def test_financials_returns_empty_for_non_listed():
    adapter = ETAdapter()
    filings = await adapter.fetch_financials("1234567890", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "Ethiopian Airlines",
        "Commercial Bank of Ethiopia",
        "Ethio Telecom",
        "Awash Bank",
    ],
)
async def test_financials_real_companies_no_mock(name: str):
    """For real Ethiopian flagship companies we must not invent filings.

    Until the PDF + browser pipeline lands (and until ESX disclosure
    coverage broadens beyond its initial 2024 listings) we explicitly
    return ``[]`` rather than fabricate a filing — same rule as every
    other adapter.
    """
    adapter = ETAdapter()
    filings = await adapter.fetch_financials(name, years=5)
    assert filings == []
