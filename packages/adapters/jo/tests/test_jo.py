"""Tests for the Jordan adapter.

Unit-level tests verify the adapter honours the no-fabrication rule for
gated registry calls and the ASE-only behaviour of `fetch_financials`.
The integration test pings the public ASE host to confirm it remains a
viable free data source for Jordanian listed-issuer filings.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.jo import JOAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = JOAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Arab Bank")


@pytest.mark.asyncio
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = JOAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "12345")


@pytest.mark.asyncio
async def test_lookup_by_trn_raises_not_implemented():
    adapter = JOAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123456789")


@pytest.mark.asyncio
async def test_lookup_invalid_trn_format():
    adapter = JOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = JOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "5493001KJTIIGC8Y1R12")


@pytest.mark.asyncio
async def test_fetch_financials_unknown_ticker_returns_empty():
    adapter = JOAdapter()
    filings = await adapter.fetch_financials("NOSUCH")
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_arab_bank_points_at_ase():
    adapter = JOAdapter()
    filings = await adapter.fetch_financials("ARBK", years=3)
    assert filings, "expected ASE filings stub for ARBK"
    assert len(filings) == 3
    for f in filings:
        assert f.company_id == "ARBK"
        assert f.currency == "JOD"
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.source_url and "ase.com.jo" in f.source_url
        assert f.structured_data is None


@pytest.mark.asyncio
async def test_fetch_financials_normalises_ticker_case():
    adapter = JOAdapter()
    filings = await adapter.fetch_financials("hikm", years=2)
    assert filings, "ticker normalisation should match HIKM"
    assert all(f.company_id == "HIKM" for f in filings)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reaches_ase():
    adapter = JOAdapter()
    health = await adapter.health_check()
    # ASE is the canonical free data source — adapter should not be in
    # ERROR state when run from a network with internet access.
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)
    assert health.capabilities["financials"] is True
