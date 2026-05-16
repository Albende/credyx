from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.pk import PKAdapter
from packages.adapters.pk.adapter import (
    PSX_LISTED,
    normalize_incorporation_number,
    normalize_ntn,
)
from packages.shared.models import IdentifierType


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


def test_psx_listed_seeds() -> None:
    # The four required real test companies must be present.
    for sym in ("HBL", "ENGRO", "PPL", "LUCK"):
        assert sym in PSX_LISTED
        assert PSX_LISTED[sym]["name"]


@pytest.mark.asyncio
async def test_search_by_name_returns_listed_hbl() -> None:
    a = PKAdapter()
    matches = await a.search_by_name("Habib")
    assert matches, "expected at least one PSX-listed match for 'Habib'"
    assert any("habib bank" in m.name.lower() for m in matches)
    assert all(m.country == "PK" for m in matches)


@pytest.mark.asyncio
async def test_search_by_name_unknown_raises_not_implemented() -> None:
    a = PKAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await a.search_by_name("no-such-pakistani-company-xyzzy")


@pytest.mark.asyncio
async def test_search_by_name_empty_returns_empty() -> None:
    a = PKAdapter()
    assert await a.search_by_name("   ") == []


@pytest.mark.asyncio
async def test_lookup_by_psx_symbol_returns_details() -> None:
    a = PKAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "HBL")
    assert details is not None
    assert details.country == "PK"
    assert "habib bank" in details.name.lower()
    assert details.capital_currency == "PKR"


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
async def test_fetch_financials_unlisted_returns_empty() -> None:
    a = PKAdapter()
    # Unknown / unlisted incorporation number → honest [].
    assert await a.fetch_financials("0012345") == []


@pytest.mark.asyncio
async def test_fetch_financials_listed_returns_empty_until_phase2() -> None:
    # PSX per-year PDF discovery needs the browser pool; until then we
    # honestly return [] rather than fabricate year-stamped entries. The
    # listing URL is still exposed via CompanyDetails.source_url.
    a = PKAdapter()
    assert await a.fetch_financials("HBL", years=3) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    a = PKAdapter()
    h = await a.health_check()
    assert h.country_code == "PK"
    assert h.capabilities.get("lookup") is True
    assert h.capabilities.get("search") is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_engro_live() -> None:
    # Listed-company lookup does not hit the network (data is from the
    # curated PSX-listed map), but mark it integration since it represents
    # real-world data linkage to PSX. Sanity-check the source URL too.
    a = PKAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "ENGRO")
    assert details is not None
    assert "engro" in details.name.lower()
    assert details.source_url and "dps.psx.com.pk" in details.source_url
