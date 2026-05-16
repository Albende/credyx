from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.bd import BDAdapter
from packages.adapters.bd.adapter import (
    DSE_LISTED,
    normalize_bin,
    normalize_registration_number,
)
from packages.shared.models import IdentifierType


# Real DSE trading symbols (publicly verifiable on dsebd.org).
GRAMEENPHONE = "GP"
BRAC_BANK = "BRACBANK"
SQUARE_PHARMA = "SQURPHARMA"
BEXIMCO_PHARMA = "BXPHARMA"


def test_normalize_registration_number_valid() -> None:
    assert normalize_registration_number("12345") == "12345"
    assert normalize_registration_number(" 12-345 ") == "12345"


def test_normalize_registration_number_rejects_alpha() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_registration_number("ABC123")


def test_normalize_registration_number_rejects_too_long() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_registration_number("12345678901")


def test_normalize_bin_accepts_9_digits() -> None:
    assert normalize_bin("123456789") == "123456789"


def test_normalize_bin_accepts_13_digits() -> None:
    assert normalize_bin("1234567890123") == "1234567890123"


def test_normalize_bin_rejects_bad_length() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_bin("12345")


def test_identifier_types() -> None:
    a = BDAdapter()
    assert a.country_code == "BD"
    assert a.country_name == "Bangladesh"
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert IdentifierType.VAT in a.identifier_types
    assert a.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


def test_dse_listed_includes_test_companies() -> None:
    for sym in (GRAMEENPHONE, BRAC_BANK, SQUARE_PHARMA, BEXIMCO_PHARMA):
        assert sym in DSE_LISTED
        assert DSE_LISTED[sym]["name"]


@pytest.mark.asyncio
async def test_search_by_name_returns_listed_match() -> None:
    a = BDAdapter()
    matches = await a.search_by_name("Grameenphone")
    assert any(m.id == GRAMEENPHONE for m in matches)
    assert all(m.country == "BD" for m in matches)


@pytest.mark.asyncio
async def test_search_by_name_by_symbol() -> None:
    a = BDAdapter()
    matches = await a.search_by_name("bracbank")
    assert any(m.id == BRAC_BANK for m in matches)


@pytest.mark.asyncio
async def test_search_by_name_empty_returns_empty() -> None:
    a = BDAdapter()
    assert await a.search_by_name("  ") == []


@pytest.mark.asyncio
async def test_search_by_name_unknown_raises_not_implemented() -> None:
    a = BDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.search_by_name("ZzzNoSuchCompanyInBangladesh")


@pytest.mark.asyncio
async def test_lookup_rejects_bad_identifier_type() -> None:
    a = BDAdapter()
    with pytest.raises(InvalidIdentifierError):
        await a.lookup_by_identifier(IdentifierType.LEI, "5493001KJTIIGC8Y1R12")


@pytest.mark.asyncio
async def test_bin_lookup_not_implemented() -> None:
    a = BDAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.lookup_by_identifier(IdentifierType.VAT, "123456789")


@pytest.mark.asyncio
async def test_lookup_dse_symbol_returns_details() -> None:
    a = BDAdapter()
    details = await a.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, GRAMEENPHONE
    )
    assert details is not None
    assert details.id == GRAMEENPHONE
    assert "grameenphone" in details.name.lower()
    assert details.country == "BD"
    assert details.capital_currency == "BDT"


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_unlisted() -> None:
    a = BDAdapter()
    # Numeric registration number → unlisted; DSE has nothing for it.
    assert await a.fetch_financials("123456") == []


@pytest.mark.asyncio
async def test_fetch_financials_listed_returns_pointers() -> None:
    a = BDAdapter()
    filings = await a.fetch_financials(SQUARE_PHARMA, years=3)
    assert len(filings) == 3
    for f in filings:
        assert f.company_id == SQUARE_PHARMA
        assert f.currency == "BDT"
        # No fabricated structured data per the no-mock-data rule.
        assert f.structured_data is None
        assert f.source_url and "dsebd.org" in f.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    a = BDAdapter()
    h = await a.health_check()
    assert h.country_code == "BD"
    assert h.name == "Bangladesh"
    assert h.rate_limit_per_minute == 30
