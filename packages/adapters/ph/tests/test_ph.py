"""Integration tests for the Philippines adapter (SEC iView + PSE Edge).

The integration tests hit real SEC iView / PSE endpoints — no fixtures, no
mocks. SEC iView's JSON shape is undocumented and occasionally rotates;
network-side tests guard structural invariants rather than exact strings.
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ph import PHAdapter
from packages.adapters.ph.adapter import (
    _normalize_sec_number,
    _normalize_tin,
    _parse_ph_date,
)
from packages.shared.models import FilingType, IdentifierType


SM_SEC = "CS200417653"
AYALA_SEC = "CS197600007"
BDO_SEC = "CS196700106"
JFC_SEC = "CS197802327"


def test_normalize_sec_number_strips_and_uppercases():
    assert _normalize_sec_number("cs200417653") == SM_SEC
    assert _normalize_sec_number("  CS-2004-17653 ") == SM_SEC
    assert _normalize_sec_number("PHCS200417653") == SM_SEC
    with pytest.raises(InvalidIdentifierError):
        _normalize_sec_number("AB")
    with pytest.raises(InvalidIdentifierError):
        _normalize_sec_number("!!!not-valid!!!")


def test_normalize_tin_validates_digits():
    assert _normalize_tin("123456789") == "123456789"
    assert _normalize_tin("123-456-789-000") == "123456789000"
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("12")
    with pytest.raises(InvalidIdentifierError):
        _normalize_tin("ABCDEFGHI")


def test_parse_ph_date_handles_common_formats():
    assert _parse_ph_date("1976-01-23") == date(1976, 1, 23)
    assert _parse_ph_date("01/23/1976") == date(1976, 1, 23)
    assert _parse_ph_date("January 23, 1976") == date(1976, 1, 23)
    assert _parse_ph_date(None) is None
    assert _parse_ph_date("not a date") is None


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = PHAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, SM_SEC)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_sm_or_returns_list():
    adapter = PHAdapter()
    matches = await adapter.search_by_name("SM Investments", limit=10)
    assert isinstance(matches, list)
    if matches:
        assert any(m.country == "PH" for m in matches)
        assert all(m.id and m.name for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_sm_by_company_number():
    adapter = PHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, SM_SEC
    )
    if details is None:
        pytest.skip("SEC iView did not return a record for SM — registry transient")
    assert details.id == SM_SEC
    assert details.country == "PH"
    assert details.name
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == SM_SEC
        for i in details.identifiers
    )
    assert details.capital_currency == "PHP"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    adapter = PHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "CS999999999"
    )
    assert details is None or details.id == "CS999999999"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_structure_for_known_secs():
    adapter = PHAdapter()
    for sec_no in (SM_SEC, AYALA_SEC, BDO_SEC, JFC_SEC):
        filings = await adapter.fetch_financials(sec_no, years=3)
        assert isinstance(filings, list)
        for f in filings:
            assert f.company_id == sec_no
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "PHP"
            assert f.document_url and f.document_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_status():
    adapter = PHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PH"
    assert health.status.value in ("ok", "error")
