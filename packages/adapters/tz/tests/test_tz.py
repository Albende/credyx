"""Integration tests for the Tanzania (TZ) adapter.

Search and lookup hit the live BRELA ORS JSON endpoint; financials hit the
live DSE Livewire financial-statement component. All network-bound tests are
marked `integration` so CI can skip them.
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
@pytest.mark.integration
async def test_search_returns_real_registry_records():
    adapter = TZAdapter()
    matches = await adapter.search_by_name("CRDB", limit=5)
    assert matches
    names = {m.name.upper() for m in matches}
    assert any("CRDB BANK" in n for n in names)
    for m in matches:
        assert m.country == "TZ"
        assert m.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number():
    adapter = TZAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "30227")
    assert details is not None
    assert details.id == "30227"
    assert "CRDB BANK" in details.name.upper()
    assert details.country == "TZ"
    assert details.incorporation_date is not None


@pytest.mark.asyncio
async def test_lookup_with_vat_not_implemented():
    adapter = TZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123-456-789")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_for_unlisted_returns_empty():
    adapter = TZAdapter()
    filings = await adapter.fetch_financials("NOT-A-DSE-TICKER", years=3)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("ticker", ["CRDB", "NMB"])
async def test_fetch_financials_returns_downloadable_pdfs(ticker: str):
    adapter = TZAdapter()
    filings = await adapter.fetch_financials(ticker, years=3)
    assert filings
    for f in filings:
        assert f.company_id == ticker
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "TZS"
        assert f.document_format == "pdf"
        assert f.document_url and f.document_url.endswith(".pdf")
        assert f"securities/{ticker}/" in f.document_url
        assert f.structured_data is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_ticker_is_case_insensitive():
    adapter = TZAdapter()
    filings = await adapter.fetch_financials("crdb", years=2)
    assert filings
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
async def test_health_check_probes_brela():
    adapter = TZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "TZ"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    if health.status == AdapterStatus.OK:
        assert health.capabilities["search"] is True
        assert health.capabilities["lookup"] is True
        assert health.capabilities["financials"] is True
