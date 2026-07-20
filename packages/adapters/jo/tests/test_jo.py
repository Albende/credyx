"""Tests for the Jordan adapter.

The adapter is backed by the Amman Stock Exchange (exchange.jo) public
listed-issuer directory and disclosure filings. Unit tests cover
identifier validation and no-fabrication behaviour for unknown issuers;
integration tests hit the real ASE host to confirm it remains a viable
free data source.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.jo import JOAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_lookup_invalid_symbol_format():
    adapter = JOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.OTHER, "!")


@pytest.mark.asyncio
async def test_lookup_invalid_code_format():
    adapter = JOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "12")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = JOAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123456789")


@pytest.mark.asyncio
async def test_fetch_financials_unknown_symbol_returns_empty():
    adapter = JOAdapter()
    filings = await adapter.fetch_financials("NOSUCH")
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_listed_issuer():
    adapter = JOAdapter()
    matches = await adapter.search_by_name("phosphate")
    assert matches, "expected an ASE match for 'phosphate'"
    top = matches[0]
    assert top.id == "JOPH"
    assert top.country == "JO"
    assert any(i.type == IdentifierType.OTHER and i.value == "JOPH" for i in top.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_symbol_returns_real_details():
    adapter = JOAdapter()
    details = await adapter.lookup_by_identifier(adapter.primary_identifier, "JOPH")
    assert details is not None
    assert details.id == "JOPH"
    assert details.country == "JO"
    assert details.capital_currency == "JOD"
    assert details.capital_amount and details.capital_amount > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_security_code_returns_real_details():
    adapter = JOAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "141018")
    assert details is not None
    assert details.id == "JOPH"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_downloadable_filings():
    adapter = JOAdapter()
    filings = await adapter.fetch_financials("JOPH", years=3)
    assert filings, "expected ASE annual-report filings for JOPH"
    years = {f.year for f in filings}
    assert len(years) == len(filings), "filings should be de-duplicated per fiscal year"
    for f in filings:
        assert f.company_id == "JOPH"
        assert f.currency == "JOD"
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.document_url and f.document_url.startswith("https://www.exchange.jo/")
        assert f.source_url and "symbol=JOPH" in f.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reaches_ase():
    adapter = JOAdapter()
    health = await adapter.health_check()
    assert health.status == AdapterStatus.OK
    assert health.capabilities["financials"] is True
