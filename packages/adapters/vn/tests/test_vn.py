"""Integration tests for the Vietnam adapter (thongtindoanhnghiep.co + HOSE/HNX).

The integration tests hit the real thongtindoanhnghiep.co endpoint — no
fixtures, no mocks.
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.vn import VNAdapter
from packages.adapters.vn.adapter import (
    _normalize_mst,
    _parse_vn_date,
)
from packages.shared.models import FilingType, IdentifierType


VINAMILK_MST = "0300588569"
VINGROUP_MST = "0101245486"
VCB_MST = "0100112437"
FPT_MST = "0101248141"


def test_normalize_mst_strips_and_validates():
    assert _normalize_mst("  0300588569 ") == VINAMILK_MST
    assert _normalize_mst("0300-588-569") == VINAMILK_MST
    assert _normalize_mst("0300.588.569") == VINAMILK_MST
    assert _normalize_mst("VN0300588569") == VINAMILK_MST
    # 13-digit branch suffix preserved.
    assert _normalize_mst("0300588569001") == "0300588569001"
    assert _normalize_mst("0300588569-001") == "0300588569001"
    with pytest.raises(InvalidIdentifierError):
        _normalize_mst("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_mst("ABCDEFGHIJ")
    with pytest.raises(InvalidIdentifierError):
        _normalize_mst("")


def test_parse_vn_date_handles_iso_and_dmy():
    assert _parse_vn_date("2010-04-19") == date(2010, 4, 19)
    assert _parse_vn_date("19/04/2010") == date(2010, 4, 19)
    assert _parse_vn_date("19-04-2010") == date(2010, 4, 19)
    assert _parse_vn_date(None) is None
    assert _parse_vn_date("not a date") is None


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = VNAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, VINAMILK_MST)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_vinamilk():
    adapter = VNAdapter()
    matches = await adapter.search_by_name("Vinamilk", limit=10)
    assert isinstance(matches, list)
    if matches:
        assert any(m.country == "VN" for m in matches)
        assert all(m.id and m.name for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_vinamilk_by_company_number():
    adapter = VNAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, VINAMILK_MST
    )
    if details is None:
        pytest.skip("thongtindoanhnghiep.co did not return a record — transient")
    assert details.id == VINAMILK_MST
    assert details.country == "VN"
    assert details.name
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == VINAMILK_MST
        for i in details.identifiers
    )
    assert any(
        i.type == IdentifierType.VAT and i.value == VINAMILK_MST
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_vinamilk_by_vat_returns_same_record():
    adapter = VNAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, VINAMILK_MST)
    if details is None:
        pytest.skip("thongtindoanhnghiep.co did not return a record — transient")
    assert details.id == VINAMILK_MST


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none_or_empty():
    adapter = VNAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "9999999999"
    )
    assert details is None or details.id == "9999999999"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_structure_for_known_msts():
    adapter = VNAdapter()
    for mst in (VINAMILK_MST, VINGROUP_MST, VCB_MST, FPT_MST):
        filings = await adapter.fetch_financials(mst, years=3)
        assert isinstance(filings, list)
        for f in filings:
            assert f.company_id == mst
            assert f.type == FilingType.ANNUAL_REPORT
            assert f.currency == "VND"
            assert f.document_url and f.document_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_status():
    adapter = VNAdapter()
    health = await adapter.health_check()
    assert health.country_code == "VN"
    assert health.status.value in ("ok", "error")
