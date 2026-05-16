"""Integration tests for the Tanzania (TZ) adapter.

BRELA/TRA endpoints are gated, so search and lookup are expected to raise
`AdapterNotImplementedError`. The DSE health probe hits a real host
(https://www.dse.co.tz/) — marked `integration` so CI can skip it.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.tz import TZAdapter
from packages.shared.models import (
    AdapterStatus,
    FilingType,
    IdentifierType,
)


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = TZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("CRDB", limit=5)


@pytest.mark.asyncio
async def test_lookup_raises_not_implemented():
    adapter = TZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "12345")


@pytest.mark.asyncio
async def test_lookup_with_vat_also_not_implemented():
    adapter = TZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123-456-789")


@pytest.mark.asyncio
async def test_fetch_financials_for_unlisted_returns_empty():
    adapter = TZAdapter()
    filings = await adapter.fetch_financials("UNKNOWN-CO", years=3)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["CRDB", "NMB", "TBL", "VODA"])
async def test_fetch_financials_for_listed_returns_dse_pointer(ticker: str):
    adapter = TZAdapter()
    filings = await adapter.fetch_financials(ticker, years=3)
    assert len(filings) == 1
    f = filings[0]
    assert f.company_id == ticker
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "TZS"
    assert f.source_url and "dse.co.tz" in f.source_url
    # No fabricated structured data — that is downstream pipeline's job.
    assert f.structured_data is None
    assert f.document_url is None


@pytest.mark.asyncio
async def test_fetch_financials_ticker_is_case_insensitive():
    adapter = TZAdapter()
    filings = await adapter.fetch_financials("crdb", years=3)
    assert len(filings) == 1
    assert filings[0].company_id == "CRDB"


@pytest.mark.asyncio
async def test_metadata():
    adapter = TZAdapter()
    assert adapter.country_code == "TZ"
    assert adapter.country_name == "Tanzania"
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_dse():
    adapter = TZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "TZ"
    # When DSE responds we report DEGRADED (search/lookup gated, financials
    # only via DSE). If the probe fails we expect ERROR.
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities["search"] is False
    assert health.capabilities["lookup"] is False
    if health.status == AdapterStatus.DEGRADED:
        assert health.capabilities["financials"] is True
