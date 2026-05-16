from __future__ import annotations

import os

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.hk import HKAdapter
from packages.adapters.hk.adapter import (
    _normalize_br_number,
    _normalize_cr_number,
    _split_packed_id,
)
from packages.shared.models import FilingType, IdentifierType


TENCENT_CR = "0654177"
AIA_CR = "1299985"
HSBC_HK_CR = "0263876"
TENCENT_HKEX = "0700"
AIA_HKEX = "1299"


def test_cr_normalize_zero_pads():
    assert _normalize_cr_number("654177") == TENCENT_CR
    assert _normalize_cr_number("0654177") == TENCENT_CR
    assert _normalize_cr_number(" 1392 ") == "0001392"
    assert _normalize_cr_number("CR:1392") == "0001392"


def test_cr_normalize_rejects_bad_format():
    with pytest.raises(InvalidIdentifierError):
        _normalize_cr_number("12345678")  # 8 digits = not a CR
    with pytest.raises(InvalidIdentifierError):
        _normalize_cr_number("ABCDEFG")


def test_br_normalize_requires_eight_digits():
    assert _normalize_br_number("12345678") == "12345678"
    with pytest.raises(InvalidIdentifierError):
        _normalize_br_number("1234567")


def test_split_packed_id_variants():
    assert _split_packed_id("0654177") == ("0654177", None)
    assert _split_packed_id("0654177/HKEX:700") == ("0654177", "0700")
    assert _split_packed_id("0654177@HKEX:700") == ("0654177", "0700")
    assert _split_packed_id("CR:1392") == ("0001392", None)
    assert _split_packed_id("garbage!!") == (None, None)


@pytest.mark.asyncio
async def test_search_without_opencorporates_raises_not_implemented(monkeypatch):
    monkeypatch.delenv("OPENCORPORATES_API_KEY", raising=False)
    adapter = HKAdapter(opencorporates_api_key=None)
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Tencent", limit=3)


@pytest.mark.asyncio
async def test_lookup_br_raises_not_implemented():
    adapter = HKAdapter(opencorporates_api_key=None)
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.OTHER, "12345678")


@pytest.mark.asyncio
async def test_lookup_rejects_other_id_types():
    adapter = HKAdapter(opencorporates_api_key=None)
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345678")


@pytest.mark.asyncio
async def test_fetch_financials_unlisted_returns_empty():
    # No HKEX hint + no OpenCorporates key => unlisted-or-unknown => [].
    adapter = HKAdapter(opencorporates_api_key=None)
    filings = await adapter.fetch_financials("0001392", years=2)
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_listed_via_packed_id():
    # Packed id supplies HKEX code directly, so no OC round-trip is needed.
    adapter = HKAdapter(opencorporates_api_key=None)
    filings = await adapter.fetch_financials(
        f"{TENCENT_CR}/HKEX:{TENCENT_HKEX}", years=3
    )
    assert len(filings) >= 3
    for f in filings:
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "HKD"
        assert f.document_url and f.document_url.startswith("https://")
        assert f"stockId={TENCENT_HKEX}" in f.document_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_icris():
    adapter = HKAdapter()
    health = await adapter.health_check()
    assert health.country_code == "HK"
    assert health.status.value in ("ok", "degraded", "error")
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_via_opencorporates():
    if not os.getenv("OPENCORPORATES_API_KEY"):
        pytest.skip("OPENCORPORATES_API_KEY not set")
    adapter = HKAdapter()
    matches = await adapter.search_by_name("Tencent Holdings", limit=5)
    assert matches, "expected at least one HK match for Tencent"
    for m in matches:
        assert m.country == "HK"
        assert any(i.type == IdentifierType.COMPANY_NUMBER for i in m.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_tencent_by_cr():
    if not os.getenv("OPENCORPORATES_API_KEY"):
        pytest.skip("OPENCORPORATES_API_KEY not set")
    adapter = HKAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, TENCENT_CR
    )
    assert details is not None
    assert details.id == TENCENT_CR
    assert details.country == "HK"
    assert "tencent" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_cr_returns_none():
    if not os.getenv("OPENCORPORATES_API_KEY"):
        pytest.skip("OPENCORPORATES_API_KEY not set")
    adapter = HKAdapter()
    # Valid CR shape but extremely unlikely to be assigned.
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "9999999"
    )
    assert details is None
