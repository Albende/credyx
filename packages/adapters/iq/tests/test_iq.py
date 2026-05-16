from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.iq import IQAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = IQAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Asia Cell")


@pytest.mark.asyncio
async def test_lookup_company_number_raises_not_implemented():
    adapter = IQAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "TASC"
        )


@pytest.mark.asyncio
async def test_lookup_vat_raises_not_implemented():
    adapter = IQAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123456789")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier_type():
    adapter = IQAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "TASC")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_company_number():
    adapter = IQAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "!!! bogus !!!"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_vat():
    adapter = IQAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "abc")


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["TASC", "BIIB", "IBSD"])
async def test_fetch_financials_listed_returns_empty(ticker: str):
    adapter = IQAdapter()
    filings = await adapter.fetch_financials(ticker)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_non_listed_returns_empty():
    adapter = IQAdapter()
    filings = await adapter.fetch_financials("123456")
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_bad_identifier():
    adapter = IQAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("")


@pytest.mark.asyncio
async def test_adapter_metadata():
    adapter = IQAdapter()
    assert adapter.country_code == "IQ"
    assert adapter.country_name == "Iraq"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.requires_api_key is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_probes_real_hosts():
    adapter = IQAdapter()
    health = await adapter.health_check()
    assert health.country_code == "IQ"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
