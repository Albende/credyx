"""Tests for the Senegal (SN) adapter.

The live test hits https://www.brvm.org/ — marked `integration` so the
unit run can skip it. Senegal has no free official registry API, so
search and identifier lookup are not implemented; we assert the
contract (correct error types) rather than fake a positive response.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.sn import SNAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = SNAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Sonatel", limit=5)


@pytest.mark.asyncio
async def test_lookup_rejects_other_identifier_types():
    adapter = SNAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "549300XYZ")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_rccm():
    adapter = SNAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "not-an-rccm")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_ninea():
    adapter = SNAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "AB")


@pytest.mark.asyncio
async def test_lookup_well_formed_rccm_raises_not_implemented():
    adapter = SNAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "SN-DKR-2003-B-1234"
        )


@pytest.mark.asyncio
async def test_lookup_well_formed_ninea_raises_not_implemented():
    adapter = SNAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "001234567")


@pytest.mark.asyncio
async def test_fetch_financials_unknown_ticker_is_empty():
    adapter = SNAdapter()
    assert await adapter.fetch_financials("UNKNOWN", years=3) == []


@pytest.mark.asyncio
async def test_fetch_financials_known_listed_issuer_is_empty_until_pdf_pipeline():
    # Sonatel (SNTS) is BRVM-listed but BRVM publishes annual reports as
    # PDFs. Until the PDF extraction pipeline lands, returning structured
    # filings would violate the "no mock data" rule.
    adapter = SNAdapter()
    assert await adapter.fetch_financials("SNTS", years=3) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_brvm():
    adapter = SNAdapter()
    health = await adapter.health_check()
    assert health.country_code == "SN"
    # Either DEGRADED (host reachable, capabilities limited) or ERROR
    # (BRVM unreachable). OK is never returned for Senegal in MVP.
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
