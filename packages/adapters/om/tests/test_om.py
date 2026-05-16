"""Integration tests for the Oman adapter.

Real-network tests probe MSX (msx.om). They are marked `integration` so CI
can skip them with `-m "not integration"`.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.om import OMAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = OMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Bank Muscat")


@pytest.mark.asyncio
async def test_lookup_by_identifier_raises_not_implemented():
    adapter = OMAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "1234567")
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "OM1234567890")


@pytest.mark.asyncio
async def test_fetch_financials_unknown_ticker_returns_empty():
    adapter = OMAdapter()
    assert await adapter.fetch_financials("UNKNOWN") == []
    assert await adapter.fetch_financials("") == []
    assert await adapter.fetch_financials("not-a-ticker") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["BKMB", "OTEL", "OOMS", "NBOB"])
async def test_fetch_financials_listed_issuers_return_pointer(ticker: str):
    adapter = OMAdapter()
    filings = await adapter.fetch_financials(ticker)
    assert len(filings) == 1
    f = filings[0]
    assert f.company_id == ticker
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "OMR"
    assert f.structured_data is None
    assert f.source_url is not None
    assert ticker in f.source_url
    assert "msx.om" in f.source_url


@pytest.mark.asyncio
async def test_fetch_financials_normalizes_case_and_whitespace():
    adapter = OMAdapter()
    filings = await adapter.fetch_financials("  bkmb  ")
    assert len(filings) == 1
    assert filings[0].company_id == "BKMB"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_msx():
    adapter = OMAdapter()
    health = await adapter.health_check()
    assert health.country_code == "OM"
    # MSX online: DEGRADED (no name/lookup implemented). Down: ERROR.
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
