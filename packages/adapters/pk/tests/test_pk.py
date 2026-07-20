from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.pk import PKAdapter
from packages.adapters.pk.adapter import (
    normalize_incorporation_number,
    normalize_ntn,
)
from packages.shared.models import FilingType, IdentifierType


def test_normalize_incorporation_number_valid() -> None:
    assert normalize_incorporation_number("12345") == "0012345"
    assert normalize_incorporation_number("0012345") == "0012345"
    assert normalize_incorporation_number(" 12345 ") == "0012345"


def test_normalize_incorporation_number_rejects_non_numeric() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_incorporation_number("ABC123")


def test_normalize_ntn_valid() -> None:
    assert normalize_ntn("1234567") == "1234567"
    assert normalize_ntn("12345678") == "12345678"
    assert normalize_ntn("1234567-8") == "1234567-8"


def test_normalize_ntn_rejects_bad_format() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_ntn("12")
    with pytest.raises(InvalidIdentifierError):
        normalize_ntn("ABC1234")


def test_identifier_types() -> None:
    a = PKAdapter()
    assert a.country_code == "PK"
    assert a.country_name == "Pakistan"
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert IdentifierType.VAT in a.identifier_types
    assert a.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_by_name_empty_returns_empty() -> None:
    a = PKAdapter()
    assert await a.search_by_name("   ") == []


@pytest.mark.asyncio
async def test_lookup_ntn_not_implemented() -> None:
    a = PKAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.lookup_by_identifier(IdentifierType.VAT, "1234567")


@pytest.mark.asyncio
async def test_lookup_rejects_bad_identifier_type() -> None:
    a = PKAdapter()
    with pytest.raises(InvalidIdentifierError):
        await a.lookup_by_identifier(IdentifierType.LEI, "5493001KJTIIGC8Y1R12")


@pytest.mark.asyncio
async def test_lookup_numeric_incorporation_not_implemented() -> None:
    a = PKAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "0012345")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_listed_hbl() -> None:
    a = PKAdapter()
    matches = await a.search_by_name("Habib Bank")
    assert matches, "expected at least one PSX-listed match for 'Habib Bank'"
    assert any("habib bank" in m.name.lower() for m in matches)
    assert all(m.country == "PK" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_unknown_raises_not_implemented() -> None:
    a = PKAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.search_by_name("no-such-pakistani-company-xyzzy")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_psx_symbol_returns_details() -> None:
    a = PKAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "HBL")
    assert details is not None
    assert details.country == "PK"
    assert "habib bank" in details.name.lower()
    assert details.capital_currency == "PKR"
    assert details.source_url and "dps.psx.com.pk" in details.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_symbol_raises() -> None:
    a = PKAdapter()
    with pytest.raises(InvalidIdentifierError):
        await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "ZZZZZZ")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_returns_filings() -> None:
    a = PKAdapter()
    filings = await a.fetch_financials("HBL", years=3)
    assert filings, "expected at least one annual filing for HBL"
    assert all(f.company_id == "HBL" for f in filings)
    assert all(f.type == FilingType.ANNUAL_REPORT for f in filings)
    assert all(f.currency == "PKR" for f in filings)
    assert all(f.structured_data and f.structured_data.get("metrics") for f in filings)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    a = PKAdapter()
    h = await a.health_check()
    assert h.country_code == "PK"
    assert h.capabilities.get("lookup") is True
    assert h.capabilities.get("search") is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_engro_live() -> None:
    a = PKAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "ENGRO")
    assert details is not None
    assert "engro" in details.name.lower()
    assert details.source_url and "dps.psx.com.pk" in details.source_url
