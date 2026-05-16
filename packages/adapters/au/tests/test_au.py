"""Integration tests for the AU (ABN Lookup) adapter.

These tests hit the real ABR JSON web service and require
`AU_ABN_LOOKUP_GUID` to be set. Marked `integration` so CI can opt-out
with `-m "not integration"`.
"""
from __future__ import annotations

import os

import pytest

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.adapters.au import AUAdapter
from packages.adapters.au.adapter import (
    _is_valid_abn_checksum,
    _normalize_abn,
    _normalize_acn,
    _strip_jsonp,
)
from packages.shared.models import IdentifierType


def test_abn_checksum_accepts_known_good():
    assert _is_valid_abn_checksum("49004028077")  # BHP
    assert _is_valid_abn_checksum("88000014675")  # Woolworths
    assert _is_valid_abn_checksum("33051775556")  # Telstra


def test_abn_checksum_rejects_bad():
    assert not _is_valid_abn_checksum("12345678901")


def test_normalize_abn_strips_prefix_and_spaces():
    assert _normalize_abn("AU 49 004 028 077") == "49004028077"


def test_normalize_acn_strips_spaces():
    assert _normalize_acn("004 028 077") == "004028077"


def test_strip_jsonp_unwraps_callback():
    raw = 'callback({"Abn":"49004028077","EntityName":"BHP GROUP LIMITED"});'
    parsed = _strip_jsonp(raw)
    assert parsed["Abn"] == "49004028077"


def test_fetch_financials_raises_not_implemented():
    adapter = AUAdapter(api_key="dummy")
    import asyncio

    with pytest.raises(AdapterNotImplementedError):
        asyncio.run(adapter.fetch_financials("49004028077"))


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("AU_ABN_LOOKUP_GUID"),
    reason="AU_ABN_LOOKUP_GUID not set",
)
async def test_search_finds_bhp():
    adapter = AUAdapter()
    matches = await adapter.search_by_name("BHP", limit=10)
    assert matches, "expected at least one BHP match"
    assert any("bhp" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("AU_ABN_LOOKUP_GUID"),
    reason="AU_ABN_LOOKUP_GUID not set",
)
async def test_lookup_bhp_by_abn():
    adapter = AUAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "49004028077")
    assert details is not None
    assert "bhp" in details.name.lower()
    assert any(i.type == IdentifierType.VAT and i.value == "49004028077" for i in details.identifiers)
