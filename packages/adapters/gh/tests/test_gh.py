"""Integration tests for the Ghana adapter.

Free coverage is the GSE-listed universe (~40 issuers): search + profile via
the key-less kwayisi GSE-API / AFX index, annual reports via AfricanFinancials.
RGD (COMPANY_NUMBER) and GRA (VAT) remain gated and must raise
``AdapterNotImplementedError``. Nothing here may fabricate data.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.gh import GHAdapter
from packages.shared.models import (
    AdapterStatus,
    FilingType,
    IdentifierType,
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_real_sources():
    adapter = GHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "GH"
    assert health.name == "Ghana"
    assert health.status in (AdapterStatus.OK, AdapterStatus.ERROR)
    if health.status is AdapterStatus.OK:
        assert health.capabilities["search"] is True
        assert health.capabilities["lookup"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_listed_issuer():
    adapter = GHAdapter()
    matches = await adapter.search_by_name("Ecobank Ghana", limit=5)
    assert matches
    assert any(m.id == "EGH" for m in matches)
    top = next(m for m in matches if m.id == "EGH")
    assert top.country == "GH"
    assert top.identifiers[0].type is IdentifierType.OTHER


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("ticker", ["MTNGH", "GCB", "EGH", "TOTAL"])
async def test_lookup_by_ticker_returns_real_profile(ticker: str):
    adapter = GHAdapter()
    details = await adapter.lookup_by_identifier(adapter.primary_identifier, ticker)
    assert details is not None
    assert details.country == "GH"
    assert details.name
    assert details.registered_address
    assert details.capital_currency == "GHS"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("ticker", ["MTNGH", "GCB", "EGH", "TOTAL"])
async def test_financials_listed_issuer_returns_real_filings(ticker: str):
    adapter = GHAdapter()
    filings = await adapter.fetch_financials(ticker, years=3)
    assert filings
    for f in filings:
        assert f.company_id == ticker
        assert f.type is FilingType.ANNUAL_REPORT
        assert f.currency == "GHS"
        assert f.source_url and "africanfinancials.com/document/" in f.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_raises_not_implemented():
    adapter = GHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "CS123456789"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_tin_raises_not_implemented():
    adapter = GHAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "C0001234567")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = GHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_ticker():
    adapter = GHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.OTHER, "!!")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_rgd_number():
    adapter = GHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "not-a-number"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_tin():
    adapter = GHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345")


@pytest.mark.asyncio
async def test_financials_rejects_non_ticker_input():
    adapter = GHAdapter()
    assert await adapter.fetch_financials("CS123456789", years=5) == []
