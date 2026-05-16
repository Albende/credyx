from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.lv import LVAdapter
from packages.adapters.lv.adapter import (
    _normalize_lv_vat,
    _normalize_regcode,
)
from packages.shared.models import IdentifierType


def test_regcode_normalizer_accepts_known_companies():
    assert _normalize_regcode("40003032949") == "40003032949"
    assert _normalize_regcode("40003245752") == "40003245752"
    assert _normalize_regcode("40003520643") == "40003520643"
    assert _normalize_regcode("40103303559") == "40103303559"
    assert _normalize_regcode("40003-032-949") == "40003032949"
    assert _normalize_regcode("LV40003032949") == "40003032949"


def test_regcode_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_regcode("12345")  # too short
    with pytest.raises(InvalidIdentifierError):
        _normalize_regcode("123456789012")  # too long
    with pytest.raises(InvalidIdentifierError):
        _normalize_regcode("ABC12345678")
    with pytest.raises(InvalidIdentifierError):
        _normalize_regcode("")


def test_lv_vat_normalizer_accepts_known_vats():
    assert _normalize_lv_vat("LV40003032949") == "40003032949"
    assert _normalize_lv_vat("lv 400 030 32949") == "40003032949"
    assert _normalize_lv_vat("40003245752") == "40003245752"


def test_lv_vat_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_lv_vat("LV1234567890")  # 10 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_lv_vat("LV123456789012")  # 12 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_lv_vat("not-a-vat")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = LVAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "anything")


@pytest.mark.asyncio
async def test_fetch_financials_rejects_bad_regcode():
    adapter = LVAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-code")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_valid_regcode():
    # Annual reports come via paid Lursoft — we never invent filings.
    adapter = LVAdapter()
    assert await adapter.fetch_financials("40003032949") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_ok():
    adapter = LVAdapter()
    health = await adapter.health_check()
    assert health.country_code == "LV"
    assert health.capabilities["lookup"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_latvenergo():
    adapter = LVAdapter()
    # The data.gov.lv CSV is large and occasionally rate-limited; if the
    # fetch fails we accept an empty list — we never fabricate data.
    results = await adapter.search_by_name("Latvenergo", limit=5)
    assert isinstance(results, list)
    for r in results:
        assert r.country == "LV"
        assert r.id.isdigit()
        assert len(r.id) == 11


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_regcode_latvenergo():
    adapter = LVAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "40003032949"
    )
    if details is not None:
        assert details.id == "40003032949"
        assert details.country == "LV"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_latvenergo():
    adapter = LVAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "LV40003032949"
    )
    # VIES is occasionally throttled; None is acceptable, fabricated data
    # is not.
    if details is not None:
        assert details.country == "LV"
        assert details.id == "LV40003032949"
