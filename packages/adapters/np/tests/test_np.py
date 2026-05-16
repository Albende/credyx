from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.np import NPAdapter
from packages.adapters.np.adapter import (
    NEPSE_LISTED,
    normalize_pan,
    normalize_registration_number,
)
from packages.shared.models import IdentifierType


# Real NEPSE trading symbols (publicly verifiable on nepalstock.com).
NABIL_BANK = "NABIL"
NEPAL_TELECOM = "NTC"
NEPAL_INVESTMENT_MEGA = "NIMB"
STANDARD_CHARTERED = "SCB"


def test_normalize_registration_number_valid() -> None:
    assert normalize_registration_number("12345") == "12345"
    assert normalize_registration_number(" 12-345 ") == "12345"
    assert normalize_registration_number("123/45") == "12345"


def test_normalize_registration_number_rejects_alpha() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_registration_number("ABC123")


def test_normalize_registration_number_rejects_too_long() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_registration_number("12345678901")


def test_normalize_pan_valid() -> None:
    assert normalize_pan("123456789") == "123456789"
    assert normalize_pan(" 123-456-789 ") == "123456789"


def test_normalize_pan_rejects_wrong_length() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_pan("12345")
    with pytest.raises(InvalidIdentifierError):
        normalize_pan("1234567890")


def test_normalize_pan_rejects_alpha() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_pan("ABC456789")


def test_identifier_types() -> None:
    a = NPAdapter()
    assert a.country_code == "NP"
    assert a.country_name == "Nepal"
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert IdentifierType.VAT in a.identifier_types
    assert a.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


def test_nepse_listed_includes_test_companies() -> None:
    for sym in (NABIL_BANK, NEPAL_TELECOM, NEPAL_INVESTMENT_MEGA, STANDARD_CHARTERED):
        assert sym in NEPSE_LISTED
        assert NEPSE_LISTED[sym]["name"]


@pytest.mark.asyncio
async def test_search_by_name_returns_listed_match() -> None:
    a = NPAdapter()
    matches = await a.search_by_name("Nabil")
    assert any(m.id == NABIL_BANK for m in matches)
    assert all(m.country == "NP" for m in matches)


@pytest.mark.asyncio
async def test_search_by_name_by_symbol() -> None:
    a = NPAdapter()
    matches = await a.search_by_name("ntc")
    assert any(m.id == NEPAL_TELECOM for m in matches)


@pytest.mark.asyncio
async def test_search_by_name_empty_returns_empty() -> None:
    a = NPAdapter()
    assert await a.search_by_name("   ") == []


@pytest.mark.asyncio
async def test_search_by_name_unknown_raises_not_implemented() -> None:
    a = NPAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.search_by_name("ZzzNoSuchCompanyInNepal")


@pytest.mark.asyncio
async def test_lookup_rejects_bad_identifier_type() -> None:
    a = NPAdapter()
    with pytest.raises(InvalidIdentifierError):
        await a.lookup_by_identifier(IdentifierType.LEI, "5493001KJTIIGC8Y1R12")


@pytest.mark.asyncio
async def test_pan_lookup_not_implemented() -> None:
    a = NPAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.lookup_by_identifier(IdentifierType.VAT, "123456789")


@pytest.mark.asyncio
async def test_lookup_nepse_symbol_returns_details() -> None:
    a = NPAdapter()
    details = await a.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, NABIL_BANK
    )
    assert details is not None
    assert details.id == NABIL_BANK
    assert "nabil" in details.name.lower()
    assert details.country == "NP"
    assert details.capital_currency == "NPR"
    assert details.source_url and "nepalstock.com" in details.source_url


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_unlisted() -> None:
    a = NPAdapter()
    # Numeric registration number → unlisted; NEPSE has nothing for it.
    assert await a.fetch_financials("123456") == []


@pytest.mark.asyncio
async def test_fetch_financials_listed_returns_pointers() -> None:
    a = NPAdapter()
    filings = await a.fetch_financials(NEPAL_TELECOM, years=3)
    assert len(filings) == 3
    for f in filings:
        assert f.company_id == NEPAL_TELECOM
        assert f.currency == "NPR"
        # No fabricated structured data per the no-mock-data rule.
        assert f.structured_data is None
        assert f.source_url and "nepalstock.com" in f.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    a = NPAdapter()
    h = await a.health_check()
    assert h.country_code == "NP"
    assert h.name == "Nepal"
    assert h.rate_limit_per_minute == 30
