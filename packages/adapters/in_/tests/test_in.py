from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.in_ import INAdapter
from packages.adapters.in_.adapter import normalize_cin
from packages.shared.models import IdentifierType


# Real CINs (publicly verifiable via mca.gov.in).
RELIANCE_CIN = "L17110MH1973PLC019786"
TCS_CIN = "L22210MH1995PLC084781"
INFOSYS_CIN = "L85110KA1981PLC013115"
HDFC_BANK_CIN = "L65920MH1994PLC080618"


def test_normalize_cin_valid() -> None:
    assert normalize_cin(RELIANCE_CIN) == RELIANCE_CIN
    assert normalize_cin(" l17110mh1973plc019786 ") == RELIANCE_CIN


def test_normalize_cin_rejects_short() -> None:
    with pytest.raises(InvalidIdentifierError):
        normalize_cin("ABC123")


def test_normalize_cin_rejects_wrong_structure() -> None:
    # 21 chars but bad layout (no listing prefix L/U).
    with pytest.raises(InvalidIdentifierError):
        normalize_cin("X17110MH1973PLC019786")


def test_identifier_types() -> None:
    a = INAdapter()
    assert a.country_code == "IN"
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert a.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_by_name_empty_returns_empty() -> None:
    a = INAdapter()
    assert await a.search_by_name("   ") == []


@pytest.mark.asyncio
async def test_lookup_rejects_bad_identifier_type() -> None:
    a = INAdapter()
    with pytest.raises(InvalidIdentifierError):
        await a.lookup_by_identifier(IdentifierType.LEI, "5493001KJTIIGC8Y1R12")


@pytest.mark.asyncio
async def test_gstin_lookup_not_implemented() -> None:
    a = INAdapter()
    # Valid GSTIN format for Reliance Industries (Maharashtra, state code 27).
    with pytest.raises(AdapterNotImplementedError):
        await a.lookup_by_identifier(IdentifierType.VAT, "27AAACR5055K1Z7")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_unlisted() -> None:
    a = INAdapter()
    # 'U' prefix → unlisted private company; no BSE/NSE filings available.
    unlisted = "U72200KA2008PTC047511"
    assert await a.fetch_financials(unlisted) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_reliance_real() -> None:
    a = INAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, RELIANCE_CIN)
    assert details is not None
    assert "reliance" in details.name.lower()
    assert details.country == "IN"
    assert details.id == RELIANCE_CIN


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_tcs_real() -> None:
    a = INAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, TCS_CIN)
    assert details is not None
    assert "tata" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_reliance_real() -> None:
    a = INAdapter()
    matches = await a.search_by_name("Reliance Industries", limit=5)
    assert matches
    hit = next(m for m in matches if m.id == RELIANCE_CIN)
    assert "reliance" in hit.name.lower()
    assert hit.country == "IN"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_reliance_real() -> None:
    a = INAdapter()
    filings = await a.fetch_financials(RELIANCE_CIN, years=3)
    assert filings
    assert all(f.company_id == RELIANCE_CIN for f in filings)
    assert all(f.document_url and f.document_url.startswith("http") for f in filings)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    a = INAdapter()
    h = await a.health_check()
    assert h.country_code == "IN"
    assert h.capabilities.get("lookup") is True
    assert h.capabilities.get("search") is True
