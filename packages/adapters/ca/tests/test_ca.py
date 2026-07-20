"""Integration tests for the Canada adapter.

These hit the Corporations Canada register JSON API + SEC EDGAR live — no
mocks. Marked `integration` so `pytest -m "not integration"` skips them.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ca import CAAdapter
from packages.adapters.ca.adapter import _normalize_bn, _normalize_corp_number
from packages.shared.models import AdapterStatus, IdentifierType

SHOPIFY_CORP_ID = "4261607"
SHOPIFY_BN = "847871746"


def test_normalize_corp_number_strips_check_digit():
    assert _normalize_corp_number("426160-7") == "4261607"
    assert _normalize_corp_number(" 102784 ") == "102784"


def test_normalize_corp_number_rejects_letters():
    with pytest.raises(InvalidIdentifierError):
        _normalize_corp_number("ABC123")


def test_normalize_corp_number_rejects_too_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_corp_number("12")


def test_normalize_bn_takes_nine_digit_stem():
    assert _normalize_bn("847871746RC0001") == "847871746"
    assert _normalize_bn("847871746") == "847871746"


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
async def test_lookup_shopify_by_corp_number():
    adapter = CAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, SHOPIFY_CORP_ID
    )
    assert details is not None
    assert "shopify" in details.name.lower()
    assert details.country == "CA"
    assert details.incorporation_date is not None
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == SHOPIFY_CORP_ID
        for i in details.identifiers
    )
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_business_number_resolves():
    adapter = CAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, f"{SHOPIFY_BN}RC0001"
    )
    assert details is not None
    assert "shopify" in details.name.lower()
    assert details.id == SHOPIFY_CORP_ID


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_corp_returns_none():
    adapter = CAAdapter()
    result = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "9999998"
    )
    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_shopify_returns_filings():
    adapter = CAAdapter()
    filings = await adapter.fetch_financials(SHOPIFY_CORP_ID, years=5)
    assert isinstance(filings, list)
    assert filings, "Shopify cross-lists on the NYSE — expected SEC annual reports"
    for f in filings:
        assert f.company_id == SHOPIFY_CORP_ID
        assert f.document_url and f.document_url.startswith("https://www.sec.gov/")
        assert f.year > 2000
