from __future__ import annotations

import os

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ie import IEAdapter
from packages.adapters.ie.adapter import _is_financial_filing, _normalize_cro_number
from packages.shared.models import IdentifierType


def test_normalize_cro_number_strips_zeros_and_spaces():
    assert _normalize_cro_number(" 0249885 ") == "249885"
    assert _normalize_cro_number("12965") == "12965"
    assert _normalize_cro_number("000012965") == "12965"


def test_normalize_cro_number_rejects_non_numeric():
    with pytest.raises(InvalidIdentifierError):
        _normalize_cro_number("12A45")
    with pytest.raises(InvalidIdentifierError):
        _normalize_cro_number("12345678")  # > 7 digits


def test_filing_type_detector():
    assert _is_financial_filing("B1 - ANNUAL RETURN")
    assert _is_financial_filing("Annual Return with Accounts")
    assert _is_financial_filing("Financial Statements")
    assert not _is_financial_filing("Change of Director")
    assert not _is_financial_filing("")


@pytest.mark.asyncio
async def test_vat_lookup_rejected():
    adapter = IEAdapter(username="x", password="y")
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "IE1234567T")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_ryanair():
    if not (os.getenv("IE_CRO_API_USERNAME") and os.getenv("IE_CRO_API_PASSWORD")):
        pytest.skip("IE_CRO_API_USERNAME / IE_CRO_API_PASSWORD not set")
    adapter = IEAdapter()
    matches = await adapter.search_by_name("Ryanair", limit=10)
    assert matches, "expected at least one match for Ryanair"
    assert any("ryanair" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ryanair_holdings_cro_249885():
    if not (os.getenv("IE_CRO_API_USERNAME") and os.getenv("IE_CRO_API_PASSWORD")):
        pytest.skip("IE_CRO_API_USERNAME / IE_CRO_API_PASSWORD not set")
    adapter = IEAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "249885")
    assert details is not None
    assert details.country == "IE"
    assert "ryanair" in details.name.lower()
    assert details.id == "249885"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_filings_for_ryanair():
    if not (os.getenv("IE_CRO_API_USERNAME") and os.getenv("IE_CRO_API_PASSWORD")):
        pytest.skip("IE_CRO_API_USERNAME / IE_CRO_API_PASSWORD not set")
    adapter = IEAdapter()
    filings = await adapter.fetch_financials("249885", years=10)
    assert len(filings) >= 1, "expected at least one annual filing in last 10 years"
    for f in filings:
        assert f.company_id == "249885"
        assert f.currency == "EUR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = IEAdapter()
    health = await adapter.health_check()
    # /status is unauthenticated — should always reach the server.
    assert health.country_code == "IE"
    assert health.requires_api_key is True
