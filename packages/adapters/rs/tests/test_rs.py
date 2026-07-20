from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.rs import RSAdapter
from packages.adapters.rs.adapter import (
    _as_int,
    _classify_status,
    _fold,
    _normalize_mb,
    _parse_rs_date,
    _to_rsd,
)
from packages.shared.models import (
    AdapterStatus,
    FilingType,
    IdentifierType,
)


def test_normalize_mb_validates_eight_digits():
    assert _normalize_mb("20084693") == "20084693"
    assert _normalize_mb(" 20084693 ") == "20084693"
    assert _normalize_mb("2008-4693") == "20084693"
    with pytest.raises(InvalidIdentifierError):
        _normalize_mb("1234567")
    with pytest.raises(InvalidIdentifierError):
        _normalize_mb("ABCDEFGH")
    with pytest.raises(InvalidIdentifierError):
        _normalize_mb("123456789")


def test_parse_rs_date_handles_iso():
    assert _parse_rs_date("2005-10-01").isoformat() == "2005-10-01"
    assert _parse_rs_date("2005-10-01T00:00:00").isoformat() == "2005-10-01"
    assert _parse_rs_date(None) is None
    assert _parse_rs_date("") is None
    assert _parse_rs_date("not-a-date") is None


def test_classify_status_maps_cyrillic_and_latin():
    assert _classify_status("Активан") == "active"
    assert _classify_status("Aktivan") == "active"
    assert _classify_status("Брисан из регистра") == "ceased"
    assert _classify_status("U likvidaciji") == "ceased"
    assert _classify_status("Стечај") == "ceased"
    assert _classify_status(None) is None


def test_fold_is_diacritic_and_case_insensitive():
    folded = _fold("DRUŠTVO Čačak Đorđe")
    assert "drustvo" in folded
    assert "cacak" in folded
    assert "djordje" in folded


def test_numeric_helpers():
    assert _as_int(5156) == 5156
    assert _as_int(None) is None
    assert _as_int(True) is None
    assert _to_rsd(482085621) == 482085621000.0
    assert _to_rsd(None) is None


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = RSAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "104052135")


@pytest.mark.asyncio
async def test_fetch_financials_validates_mb():
    adapter = RSAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-mb")


def test_adapter_capabilities_and_metadata():
    adapter = RSAdapter()
    assert adapter.country_code == "RS"
    assert adapter.country_name == "Serbia"
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30
    assert adapter.identifier_types == [IdentifierType.COMPANY_NUMBER]
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = RSAdapter()
    health = await adapter.health_check()
    assert health.country_code == "RS"
    assert health.requires_api_key is False
    assert health.status in (
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_nis_by_mb():
    adapter = RSAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "20084693"
    )
    assert details is not None
    assert details.country == "RS"
    assert details.id == "20084693"
    assert "NAFTNA INDUSTRIJA SRBIJE" in details.name.upper()
    assert details.status == "active"
    assert details.nace_codes == ["0610"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = RSAdapter()
    matches = await adapter.search_by_name("Telekom Srbija")
    assert matches
    assert any("TELEKOM" in m.name.upper() for m in matches)
    assert all(m.country == "RS" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_nis_returns_annual_report():
    adapter = RSAdapter()
    filings = await adapter.fetch_financials("20084693", years=3)
    assert filings
    f = filings[0]
    assert f.company_id == "20084693"
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "RSD"
    assert f.structured_data["balance_sheet"]["total_assets"] > 0
    assert f.structured_data["income_statement"]["revenue"] > 0
