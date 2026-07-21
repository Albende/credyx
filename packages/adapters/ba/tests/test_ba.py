from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ba import BAAdapter
from packages.adapters.ba.adapter import (
    _legal_form_from_name,
    _normalize_code,
    _parse_amount,
    _parse_ba_date,
    _status_from_name,
)
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_code_ok():
    assert _normalize_code("TLKM") == "TLKM"
    assert _normalize_code(" tlkm ") == "TLKM"


def test_normalize_code_rejects_bad():
    with pytest.raises(InvalidIdentifierError):
        _normalize_code("has space")
    with pytest.raises(InvalidIdentifierError):
        _normalize_code("")


def test_status_from_name():
    assert _status_from_name("Foo a.d. - u stečaju") == "Bankruptcy (u stečaju)"
    assert _status_from_name("Telekom Srpske a.d. Banja Luka") == "Listed"


def test_legal_form_from_name():
    assert _legal_form_from_name("Telekom Srpske a.d. Banja Luka") is not None
    assert _legal_form_from_name("Nekakvo Something") is None


def test_parse_ba_date_dot_format():
    assert _parse_ba_date("31.12.2023") is not None
    assert _parse_ba_date("31.12.2023.").year == 2023


def test_parse_ba_date_none():
    assert _parse_ba_date(None) is None
    assert _parse_ba_date("garbage") is None


def test_parse_amount_local_format():
    assert _parse_amount("1.716.946.086") == 1716946086.0
    assert _parse_amount("1.234.567,89 KM") == 1234567.89
    assert _parse_amount(None) is None


def test_adapter_metadata():
    a = BAAdapter()
    assert a.country_code == "BA"
    assert a.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reachable():
    health = await BAAdapter().health_check()
    assert health.country_code == "BA"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_telekom():
    adapter = BAAdapter()
    matches = await adapter.search_by_name("telekom", limit=5)
    assert isinstance(matches, list)
    assert any(m.id == "TLKM" for m in matches)
    for m in matches:
        assert m.country == "BA"


@pytest.mark.asyncio
async def test_lookup_wrong_type_raises():
    adapter = BAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "TLKM")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_telekom():
    adapter = BAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "TLKM"
    )
    assert details is not None
    assert details.country == "BA"
    assert any(i.value == "TLKM" for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_has_real_data():
    adapter = BAAdapter()
    out = await adapter.fetch_financials("TLKM", years=3)
    assert len(out) >= 1
    assert all(f.currency == "BAM" for f in out)
    assert all("blberza.com" in (f.source_url or "") for f in out)
    latest = out[0]
    assert latest.structured_data is not None
    assert latest.structured_data["balance_sheet"]["total_assets"] > 0
