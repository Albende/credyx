"""Integration tests for the Zimbabwe adapter.

These hit the live Zimbabwe Stock Exchange website. Marked `integration`
so CI can opt-out with `-m "not integration"`.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.zw import ZWAdapter
from packages.shared.models import (
    AdapterStatus,
    FilingType,
    IdentifierType,
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_zse_reachable() -> None:
    adapter = ZWAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ZW"
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)
    assert health.capabilities["search"] is True
    assert health.capabilities["lookup"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_listed_issuer() -> None:
    adapter = ZWAdapter()
    matches = await adapter.search_by_name("Econet", limit=10)
    assert matches, "expected at least one ZSE match for 'Econet'"
    assert any("econet" in m.name.lower() for m in matches)
    assert all(m.country == "ZW" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_unknown_returns_empty() -> None:
    adapter = ZWAdapter()
    matches = await adapter.search_by_name(
        "definitely-not-a-real-zimbabwean-company-zzz", limit=5
    )
    assert matches == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_not_implemented() -> None:
    adapter = ZWAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "ABC1234"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_bpn_not_implemented() -> None:
    adapter = ZWAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "1234567890")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_for_listed_ticker() -> None:
    adapter = ZWAdapter()
    matches = await adapter.search_by_name("Delta Corporation", limit=10)
    if not matches:
        pytest.skip("Delta Corporation not present in current ZSE listings page")
    ticker = matches[0].id
    filings = await adapter.fetch_financials(ticker, years=3)
    assert filings, f"expected at least one filing entry for {ticker}"
    f = filings[0]
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "USD"
    assert f.source_url and f.source_url.startswith("https://www.zse.co.zw")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_unknown_ticker_returns_empty() -> None:
    adapter = ZWAdapter()
    filings = await adapter.fetch_financials("ZZZZ", years=3)
    assert filings == []
