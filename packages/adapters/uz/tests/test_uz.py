from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.uz import UZAdapter
from packages.adapters.uz.adapter import _normalize_inn
from packages.shared.models import FilingType, IdentifierType

# A real listed issuer on openinfo.uz — "Hamkorbank" ATB.
HAMKORBANK_INN = "200242936"


def test_normalize_inn_strips_prefix_and_whitespace():
    assert _normalize_inn("207056720") == "207056720"
    assert _normalize_inn(" 207056720 ") == "207056720"
    assert _normalize_inn("UZ207056720") == "207056720"
    assert _normalize_inn("uz 207056720") == "207056720"
    assert _normalize_inn("207-056-720") == "207056720"


def test_normalize_inn_rejects_invalid_lengths():
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("2070567200")  # 10 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("20705672A")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = UZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "207056720")


@pytest.mark.asyncio
async def test_lookup_validates_inn_shape_before_failing():
    adapter = UZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-an-inn")


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_id():
    adapter = UZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("garbage")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_live():
    adapter = UZAdapter()
    matches = await adapter.search_by_name("Hamkorbank", limit=5)
    assert matches, "expected at least one match for Hamkorbank"
    hit = next(m for m in matches if m.id == HAMKORBANK_INN)
    assert hit.country == "UZ"
    assert any(i.value == HAMKORBANK_INN for i in hit.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_identifier_live():
    adapter = UZAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, HAMKORBANK_INN
    )
    assert details is not None
    assert details.id == HAMKORBANK_INN
    assert "Hamkorbank" in details.name
    assert details.registered_address


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_live():
    adapter = UZAdapter()
    filings = await adapter.fetch_financials(HAMKORBANK_INN, years=3)
    assert filings, "expected at least one filed annual report"
    top = filings[0]
    assert top.company_id == HAMKORBANK_INN
    assert top.currency == "UZS"
    assert top.type == FilingType.ANNUAL_REPORT
    assert top.structured_data and top.structured_data.get("balance_sheet")
    assert top.source_url and top.source_url.startswith("https://openinfo.uz")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_ok():
    adapter = UZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "UZ"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30
    assert health.status.value in {"ok", "degraded"}
    assert health.capabilities["financials"] is True
