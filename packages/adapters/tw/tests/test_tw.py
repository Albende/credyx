from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.tw import TWAdapter
from packages.adapters.tw.adapter import _normalize_ubn, _validate_ubn_checksum
from packages.shared.models import FilingType, IdentifierType


TSMC_UBN = "22099131"
HONHAI_UBN = "04541302"
MEDIATEK_UBN = "23362910"


def test_ubn_checksum_valid_real_companies():
    for ubn in (TSMC_UBN, HONHAI_UBN, MEDIATEK_UBN, "23638777"):
        assert _validate_ubn_checksum(ubn), f"expected {ubn} to be valid"


def test_ubn_normalize_rejects_bad_format():
    with pytest.raises(InvalidIdentifierError):
        _normalize_ubn("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_ubn("ABCDEFGH")


def test_ubn_normalize_strips_separators():
    assert _normalize_ubn(" 2209-9131 ") == TSMC_UBN


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_ubn_returns_tsmc():
    adapter = TWAdapter()
    matches = await adapter.search_by_name(TSMC_UBN, limit=5)
    assert len(matches) == 1
    assert matches[0].id == TSMC_UBN
    assert "台" in matches[0].name or "Taiwan" in matches[0].name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_freetext_name_returns_matches():
    adapter = TWAdapter()
    matches = await adapter.search_by_name("台灣積體電路", limit=5)
    assert matches
    assert any(m.id == TSMC_UBN for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_tsmc_by_ubn():
    adapter = TWAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, TSMC_UBN)
    assert details is not None
    assert details.id == TSMC_UBN
    assert details.country == "TW"
    assert details.name  # non-empty
    assert any(
        tok in details.name for tok in ("台積", "台灣積體", "Taiwan Semiconductor")
    )
    assert any(i.type == IdentifierType.VAT and i.value == TSMC_UBN for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    adapter = TWAdapter()
    # Valid checksum but unassigned UBN.
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "00000000")
    assert details is None or details.id == "00000000"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_tsmc_structure():
    adapter = TWAdapter()
    filings = await adapter.fetch_financials(TSMC_UBN, years=3)
    assert isinstance(filings, list)
    assert filings, "TSMC is TWSE-listed and must return a filing"
    for f in filings:
        assert f.company_id == TSMC_UBN
        assert f.type in (FilingType.ANNUAL_REPORT, FilingType.BALANCE_SHEET)
        assert f.year > 2000
        assert f.currency == "TWD"
        assert f.source_url and f.source_url.startswith("https://")
        sd = f.structured_data or {}
        assert sd.get("income_statement", {}).get("revenue")
        assert sd.get("balance_sheet", {}).get("total_assets")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = TWAdapter()
    health = await adapter.health_check()
    assert health.country_code == "TW"
    assert health.status.value in ("ok", "error")
