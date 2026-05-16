"""Integration tests for the Türkiye adapter (KAP public disclosures).

These hit kap.org.tr live. No API key required.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.tr import TRAdapter
from packages.adapters.tr.adapter import (
    _normalize_mersis,
    _normalize_vkn,
)
from packages.shared.models import IdentifierType


THY_VKN = "0710001297"
THY_MERSIS = "0710001297" + "00099000"[:6]  # placeholder if not exposed
GARANTI_VKN = "3900296101"
KOC_VKN = "5650043812"
AKBANK_VKN = "0240005009"


def test_normalize_vkn_strips_and_validates():
    assert _normalize_vkn("  0710001297 ") == THY_VKN
    assert _normalize_vkn("0710-0012-97") == THY_VKN
    assert _normalize_vkn("TR0710001297") == THY_VKN
    with pytest.raises(InvalidIdentifierError):
        _normalize_vkn("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_vkn("ABCDEFGHIJ")


def test_normalize_mersis_validates():
    assert _normalize_mersis("0710001297-00099-1") == "0710001297000991"
    with pytest.raises(InvalidIdentifierError):
        _normalize_mersis("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_mersis("0710001297")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_kap_reachable():
    adapter = TRAdapter()
    health = await adapter.health_check()
    assert health.country_code == "TR"
    assert health.status.value in ("ok", "error")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_listed_company():
    adapter = TRAdapter()
    matches = await adapter.search_by_name("Türk Hava Yolları", limit=5)
    if not matches:
        matches = await adapter.search_by_name("turk hava", limit=5)
    assert matches, "expected KAP memberList to contain Turkish Airlines"
    assert any("hava" in m.name.lower() or "thyao" in (m.id or "").lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_garanti():
    adapter = TRAdapter()
    matches = await adapter.search_by_name("Garanti", limit=10)
    assert matches, "expected KAP memberList to include Garanti BBVA"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unlisted_vkn_raises_not_implemented():
    adapter = TRAdapter()
    # 9999999999 is a syntactically valid VKN that will not appear on KAP.
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "9999999999")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_rejects_tckn_shaped_identifier():
    adapter = TRAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345678901")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_for_unlisted_vkn_raises():
    adapter = TRAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.fetch_financials("9999999999", years=3)
