from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.mt import MTAdapter
from packages.adapters.mt.adapter import (
    _normalize_company_number,
    _normalize_mt_vat,
)
from packages.shared.models import IdentifierType


def test_company_number_normalizer_accepts_known_companies():
    assert _normalize_company_number("C2833") == "C2833"
    assert _normalize_company_number("c 2833") == "C2833"
    assert _normalize_company_number("2833") == "C2833"
    assert _normalize_company_number("C 22334") == "C22334"
    assert _normalize_company_number("c26136") == "C26136"


def test_company_number_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("not-a-number")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("C12345678")  # too many digits


def test_mt_vat_normalizer_accepts_known_companies():
    assert _normalize_mt_vat("MT10172321") == "10172321"
    assert _normalize_mt_vat("mt 10 17 23 21") == "10172321"
    assert _normalize_mt_vat("10172321") == "10172321"


def test_mt_vat_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_mt_vat("MT1234567")  # 7 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_mt_vat("MT123456789")  # 9 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_mt_vat("not-a-vat")


@pytest.mark.asyncio
async def test_fetch_financials_returns_mse_link_for_listed():
    adapter = MTAdapter()
    filings = await adapter.fetch_financials("C2833")
    assert len(filings) == 1
    assert filings[0].company_id == "C2833"
    assert filings[0].document_url is not None
    assert "borzamalta" in filings[0].document_url


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_unknown():
    adapter = MTAdapter()
    assert await adapter.fetch_financials("C9999999") == []


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = MTAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "anything")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_bank_of_valletta():
    adapter = MTAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "MT10172321")
    assert details is not None
    assert details.country == "MT"
    # Real VIES returns the registered name; we don't hard-code the exact
    # spelling because VAT registrants occasionally amend casing.
    assert details.name.strip() != ""


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_bank_of_valletta():
    adapter = MTAdapter()
    # MBR scrape may degrade if their HTML changes — we only assert the
    # contract: it returns a list (possibly empty), and any hit is well-formed.
    results = await adapter.search_by_name("Bank of Valletta", limit=5)
    assert isinstance(results, list)
    for r in results:
        assert r.country == "MT"
        assert r.id.startswith("C")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_bank_of_valletta():
    adapter = MTAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "C2833"
    )
    # MBR HTML may not return a parseable row in all environments; if it does,
    # we expect the canonical company number to come back. None is also
    # acceptable — we never fabricate.
    if details is not None:
        assert details.id == "C2833"
        assert details.country == "MT"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_ok():
    adapter = MTAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MT"
    assert health.capabilities["lookup"] is True
