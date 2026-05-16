from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ch import CHAdapter
from packages.adapters.ch.adapter import _format_uid, _normalize_uid
from packages.shared.models import IdentifierType


def test_normalize_uid_accepts_formatted_and_bare():
    assert _normalize_uid("CHE-105.927.350") == "105927350"
    assert _normalize_uid("che 105 927 350") == "105927350"
    assert _normalize_uid("CHE-105.927.350 MWST") == "105927350"
    assert _normalize_uid("CHE-100.077.366 TVA") == "100077366"


def test_normalize_uid_rejects_too_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_uid("CHE-105.927")


def test_normalize_uid_rejects_non_digits():
    with pytest.raises(InvalidIdentifierError):
        _normalize_uid("CHE-ABC.927.350")


def test_format_uid_roundtrip():
    assert _format_uid("105927350") == "CHE-105.927.350"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_nestle():
    adapter = CHAdapter()
    matches = await adapter.search_by_name("Nestle", limit=5)
    assert matches, "Zefix returned no results for Nestle"
    assert any("nestl" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_nestle_by_uid():
    adapter = CHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "CHE-105.927.350"
    )
    assert details is not None
    assert "nestl" in details.name.lower()
    assert details.country == "CH"
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_roche_by_vat():
    adapter = CHAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "CHE-100.077.366 MWST"
    )
    assert details is not None
    assert "roche" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_empty():
    adapter = CHAdapter()
    filings = await adapter.fetch_financials("105927350")
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = CHAdapter()
    health = await adapter.health_check()
    assert health.country_code == "CH"
    assert health.status.value in {"ok", "error"}
