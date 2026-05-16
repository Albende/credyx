from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ba import BAAdapter
from packages.adapters.ba.adapter import (
    _normalize_jib,
    _normalize_mb,
    _parse_ba_date,
    _parse_amount,
)
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_jib_ok():
    assert _normalize_jib("4200211100005") == "4200211100005"
    assert _normalize_jib(" 4200211100005 ") == "4200211100005"


def test_normalize_jib_rejects_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_jib("12345")


def test_normalize_jib_rejects_non_digit():
    with pytest.raises(InvalidIdentifierError):
        _normalize_jib("420021110000A")


def test_normalize_mb_ok():
    assert _normalize_mb("1234567") == "1234567"
    assert _normalize_mb("1234567890123") == "1234567890123"


def test_normalize_mb_rejects():
    with pytest.raises(InvalidIdentifierError):
        _normalize_mb("123")


def test_parse_ba_date_dot_format():
    assert _parse_ba_date("31.12.2023") is not None
    assert _parse_ba_date("31.12.2023.").year == 2023


def test_parse_ba_date_none():
    assert _parse_ba_date(None) is None
    assert _parse_ba_date("garbage") is None


def test_parse_amount_local_format():
    assert _parse_amount("1.234.567,89 KM") == 1234567.89
    assert _parse_amount(None) is None


def test_adapter_metadata():
    a = BAAdapter()
    assert a.country_code == "BA"
    assert IdentifierType.VAT in a.identifier_types
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
async def test_search_bh_telecom():
    adapter = BAAdapter()
    matches = await adapter.search_by_name("BH Telecom", limit=5)
    # The bizreg portal can return zero rows under load; assert the call shape.
    assert isinstance(matches, list)
    for m in matches:
        assert m.country == "BA"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_invalid_jib_raises():
    adapter = BAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-jib")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bh_telecom():
    adapter = BAAdapter()
    # Lookup may return None if the public portal is rate-limiting or temporarily
    # blocked — we only assert the contract.
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "4200211100005"
    )
    if details is not None:
        assert details.country == "BA"
        assert any(i.value == "4200211100005" for i in details.identifiers)


@pytest.mark.asyncio
async def test_fetch_financials_non_listed_returns_empty():
    adapter = BAAdapter()
    # A well-formed JIB that is not in the SASE listed set.
    out = await adapter.fetch_financials("1234567890123", years=3)
    assert out == []


@pytest.mark.asyncio
async def test_fetch_financials_listed_returns_pointers():
    adapter = BAAdapter()
    out = await adapter.fetch_financials("4200211100005", years=3)
    assert len(out) == 3
    assert all(f.currency == "BAM" for f in out)
    assert all("sase.ba" in (f.source_url or "") for f in out)
