from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.dz import DZAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_cosob():
    adapter = DZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "DZ"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_listed_issuer():
    adapter = DZAdapter()
    matches = await adapter.search_by_name("Saidal")
    assert any(m.id == "SAI" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_symbol_returns_details():
    adapter = DZAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.OTHER, "SAI")
    assert details is not None
    assert details.country == "DZ"
    assert details.capital_amount and details.capital_amount > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_real_filings():
    adapter = DZAdapter()
    filings = await adapter.fetch_financials("SAI", years=3)
    assert len(filings) >= 1
    latest = filings[0]
    assert latest.type == FilingType.ANNUAL_REPORT
    assert latest.currency == "DZD"
    assert latest.document_url and latest.document_url.endswith(".pdf")


@pytest.mark.asyncio
async def test_lookup_invalid_nif_format_raises():
    adapter = DZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345")


@pytest.mark.asyncio
async def test_lookup_valid_nif_raises_not_implemented():
    """A well-formed NIF normalises but DGI validator is login-gated."""
    adapter = DZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "000016000000000")


@pytest.mark.asyncio
async def test_lookup_rc_raises_not_implemented():
    adapter = DZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "16/00-0123456 B 09"
        )


@pytest.mark.asyncio
async def test_fetch_financials_nif_returns_empty():
    """A well-formed NIF that is not a listed issuer has no free public filings."""
    adapter = DZAdapter()
    filings = await adapter.fetch_financials("000016000000000", years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_empty_id():
    adapter = DZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("   ", years=3)
