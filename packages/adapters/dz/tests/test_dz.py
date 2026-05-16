from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.dz import DZAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_sgbv():
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
async def test_search_by_name_raises_not_implemented():
    adapter = DZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Saidal Group", limit=5)


@pytest.mark.asyncio
async def test_lookup_invalid_nif_format_raises():
    adapter = DZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345")


@pytest.mark.asyncio
async def test_lookup_valid_nif_raises_not_implemented():
    """A well-formed NIF normalises but DGI validator is not free-API."""
    adapter = DZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "000016000000000"
        )


@pytest.mark.asyncio
async def test_lookup_rc_raises_not_implemented():
    adapter = DZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "16/00-0123456 B 09"
        )


@pytest.mark.asyncio
async def test_lookup_unsupported_identifier_raises():
    adapter = DZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_fetch_financials_nif_returns_empty():
    """SGBV pages key on ticker not NIF; no resolver in MVP."""
    adapter = DZAdapter()
    # Alliance Assurances — SGBV-listed (placeholder NIF, format only).
    filings = await adapter.fetch_financials("000016000000000", years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rc_returns_empty():
    adapter = DZAdapter()
    filings = await adapter.fetch_financials("16/00-0123456 B 09", years=3)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_id():
    adapter = DZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("??", years=3)
