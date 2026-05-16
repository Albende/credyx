from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.lk import LKAdapter
from packages.shared.models import (
    AdapterStatus,
    FilingType,
    IdentifierType,
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_hits_cse():
    adapter = LKAdapter()
    health = await adapter.health_check()
    assert health.country_code == "LK"
    assert health.status == AdapterStatus.OK
    assert health.capabilities["search"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_resolves_john_keells():
    adapter = LKAdapter()
    matches = await adapter.search_by_name("John Keells Holdings", limit=5)
    assert matches, "expected at least one CSE match for John Keells"
    assert any("KEELLS" in m.name.upper() for m in matches)
    assert matches[0].country == "LK"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_resolves_dialog_axiata():
    adapter = LKAdapter()
    matches = await adapter.search_by_name("Dialog Axiata", limit=3)
    assert any("DIALOG" in m.name.upper() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_unknown_company_raises_not_implemented():
    adapter = LKAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Some Tiny Private Sole Proprietorship Pvt Ltd")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_cse_ticker_returns_details():
    adapter = LKAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "JKH"
    )
    assert details is not None
    assert "KEELLS" in details.name.upper()
    assert details.country == "LK"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_drc_number_not_implemented():
    adapter = LKAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "PV12345"
        )


@pytest.mark.asyncio
async def test_lookup_invalid_identifier_format():
    adapter = LKAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "@@not_a_thing@@"
        )


@pytest.mark.asyncio
async def test_lookup_tin_rejects_short_value():
    adapter = LKAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_jkh_annual_pdfs():
    adapter = LKAdapter()
    filings = await adapter.fetch_financials("JKH", years=10)
    assert filings, "expected at least one JKH annual report on CSE"
    f = filings[0]
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "LKR"
    assert f.document_url and f.document_url.startswith("https://cdn.cse.lk/")
    assert f.document_format == "pdf"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_non_listed_company_is_empty():
    adapter = LKAdapter()
    filings = await adapter.fetch_financials("PV12345")
    assert filings == []
