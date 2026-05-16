"""Integration tests for the BE adapter — KBO public page + NBB CBSO API.

These tests hit real public services. They are slow and marked `integration`.
"""
from __future__ import annotations

import pytest

from packages.adapters.be import BEAdapter
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ab_inbev_by_vat():
    adapter = BEAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "BE0417497106")
    assert details is not None
    assert "inbev" in details.name.lower()
    assert details.country == "BE"
    assert details.status and "active" in details.status.lower()
    assert any(i.type == IdentifierType.VAT and i.value == "BE0417497106" for i in details.identifiers)
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == "0417.497.106"
        for i in details.identifiers
    )
    assert details.nace_codes


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_accepts_dotted_form():
    adapter = BEAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "0417.497.106")
    assert details is not None
    assert "inbev" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_financials_ab_inbev_has_filings():
    adapter = BEAdapter()
    filings = await adapter.fetch_financials("BE0417497106", years=5)
    assert len(filings) >= 3, f"expected >=3 AB InBev filings, got {len(filings)}"
    f = filings[0]
    assert f.company_id == "0417497106"
    assert f.document_url and "broker/public/deposits/pdf/" in f.document_url
    assert f.document_format == "pdf"
    assert f.period_end is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_solvay():
    adapter = BEAdapter()
    matches = await adapter.search_by_name("Solvay", limit=10)
    assert matches, "expected at least one match for Solvay"
    assert any("solvay" in m.name.lower() for m in matches)
    assert all(m.country == "BE" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = BEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BE"
    assert health.status.value in ("ok", "degraded")
