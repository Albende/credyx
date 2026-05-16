"""Integration tests for the Canada adapter.

These hit Corporations Canada (ic.gc.ca) and SEDAR+ live — no mocks.
Marked `integration` so `pytest -m "not integration"` skips them.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ca import CAAdapter
from packages.adapters.ca.adapter import _normalize_corp_number
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_corp_number_strips_check_digit():
    assert _normalize_corp_number("763869-7") == "7638697"
    assert _normalize_corp_number(" 285105 ") == "285105"


def test_normalize_corp_number_rejects_letters():
    with pytest.raises(InvalidIdentifierError):
        _normalize_corp_number("ABC123")


def test_normalize_corp_number_rejects_too_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_corp_number("12")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reaches_corporations_canada():
    adapter = CAAdapter()
    health = await adapter.health_check()
    assert health.country_code == "CA"
    assert health.status in (AdapterStatus.OK, AdapterStatus.ERROR)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_shopify():
    adapter = CAAdapter()
    matches = await adapter.search_by_name("Shopify", limit=10)
    assert matches, "expected at least one match for Shopify"
    assert any("shopify" in m.name.lower() for m in matches)
    for m in matches:
        assert m.country == "CA"
        assert any(i.type == IdentifierType.COMPANY_NUMBER for i in m.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bombardier_by_corp_number():
    adapter = CAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "285105-9"
    )
    assert details is not None, "Bombardier federal corp # should resolve"
    assert "bombardier" in details.name.lower()
    assert details.country == "CA"
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == "2851059"
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_corp_returns_none_or_empty_name():
    adapter = CAAdapter()
    result = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "99999999"
    )
    assert result is None or not result.name


@pytest.mark.asyncio
async def test_lookup_business_number_raises():
    adapter = CAAdapter()
    from packages.adapters._base.errors import AdapterError

    with pytest.raises(AdapterError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "123456789RC0001"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_shopify_returns_list():
    adapter = CAAdapter()
    # Shopify is on SEDAR+. If the SEDAR endpoint shape shifts, we still
    # expect a list (possibly empty) — never an exception.
    filings = await adapter.fetch_financials("763869-7", years=3)
    assert isinstance(filings, list)
    for f in filings:
        assert f.currency == "CAD"
        assert f.company_id
