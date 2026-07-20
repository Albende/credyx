"""Integration tests for the Singapore adapter (ACRA via data.gov.sg + SGX).

Real-API tests. No auth required.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.sg import SGAdapter
from packages.adapters.sg.adapter import _normalize_uen
from packages.shared.models import IdentifierType


DBS_UEN = "199901152M"
SINGTEL_UEN = "199201624D"
WILMAR_UEN = "199904785Z"
CAPITALAND_UEN = "200308573K"


def test_normalize_uen_strips_and_validates():
    assert _normalize_uen("  199901152m ") == DBS_UEN
    assert _normalize_uen("T19LL1234a") == "T19LL1234A"
    assert _normalize_uen("S12LL0001D") == "S12LL0001D"
    with pytest.raises(InvalidIdentifierError):
        _normalize_uen("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_uen("THIS_IS_NOT_A_UEN")
    with pytest.raises(InvalidIdentifierError):
        _normalize_uen("")


def test_only_company_number_identifier_supported():
    adapter = SGAdapter()
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_dbs():
    adapter = SGAdapter()
    matches = await adapter.search_by_name("DBS", limit=10)
    assert matches, "expected ACRA CKAN search to return DBS-related entities"
    assert any("dbs" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_dbs_by_uen():
    adapter = SGAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, DBS_UEN
    )
    assert details is not None
    assert details.id == DBS_UEN
    assert details.country == "SG"
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == DBS_UEN
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_uen_returns_none():
    adapter = SGAdapter()
    # Syntactically valid but extremely unlikely to ever exist.
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "999999999Z"
    )
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_financials_dbs_best_effort():
    adapter = SGAdapter()
    filings = await adapter.fetch_financials(DBS_UEN, years=5)
    # SGX may or may not surface a UEN-matched listing for a given issuer at
    # any given time; this test asserts the call doesn't crash and that any
    # returned filings are well-formed. Empty is acceptable per spec — never
    # invent data.
    assert isinstance(filings, list)
    for f in filings:
        assert f.company_id == DBS_UEN
        # SGX's financial-reports feed carries no currency field; we leave it
        # unset rather than assume SGD (some issuers, e.g. Wilmar, report USD).
        assert f.currency is None or f.currency in {"SGD", "USD"}
        assert f.year >= 2000
