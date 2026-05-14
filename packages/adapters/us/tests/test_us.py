"""Integration tests for the US (SEC EDGAR) adapter.

These tests hit real SEC endpoints. They take a few seconds. Marked
`integration` so CI can opt-out with `-m "not integration"`.
"""
from __future__ import annotations

import pytest

from packages.adapters.us import USAdapter
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_apple():
    adapter = USAdapter()
    matches = await adapter.search_by_name("Apple Inc.", limit=5)
    assert any("apple" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_apple_cik():
    adapter = USAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.CIK, "0000320193")
    assert details is not None
    assert "apple" in details.name.lower()
    assert any(i.type == IdentifierType.CIK for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_financials_apple_have_xbrl():
    adapter = USAdapter()
    filings = await adapter.fetch_financials("0000320193", years=3)
    assert filings, "expected at least one Apple 10-K filing"
    f = filings[0]
    assert f.structured_data, "Apple filings should have structured XBRL data"
    # Apple consistently reports these tags.
    assert "revenue" in f.structured_data or "total_assets" in f.structured_data
