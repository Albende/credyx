from __future__ import annotations

import pytest

from packages.adapters.bw import BWAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_financials_unknown_ticker_returns_empty():
    adapter = BWAdapter()
    assert await adapter.fetch_financials("UNKNOWN_TICKER") == []


@pytest.mark.asyncio
async def test_financials_empty_id_returns_empty():
    adapter = BWAdapter()
    assert await adapter.fetch_financials("") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_returns_real_companies():
    adapter = BWAdapter()
    matches = await adapter.search_by_name("Sefalana", limit=5)
    assert matches
    top = matches[0]
    assert top.country == "BW"
    assert top.id.startswith("BW")
    assert top.identifiers[0].type == IdentifierType.COMPANY_NUMBER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_number_returns_details():
    adapter = BWAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "BW00001731678"
    )
    assert details is not None
    assert "Sefalana" in details.name
    assert details.incorporation_date is not None
    assert details.identifiers[0].value == "BW00001731678"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_number_returns_none():
    adapter = BWAdapter()
    assert (
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "BW99999999999"
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("ticker", ["SEFA", "LETSHEGO", "CHOPPIES"])
async def test_financials_listed_ticker_returns_real_filings(ticker: str):
    adapter = BWAdapter()
    filings = await adapter.fetch_financials(ticker, years=3)
    assert filings
    f = filings[0]
    assert f.type in {FilingType.ANNUAL_REPORT, FilingType.AUDIT_REPORT}
    assert f.currency == "BWP"
    assert f.document_url and f.document_url.endswith(".pdf")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_sources():
    adapter = BWAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BW"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
