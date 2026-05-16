from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.gr import GRAdapter
from packages.adapters.gr.adapter import (
    _afm_checksum_ok,
    _normalize_afm,
    _normalize_gemi,
)
from packages.shared.models import IdentifierType


def test_afm_checksum_valid_for_known_companies():
    # ΑΦΜ values for real Greek listed entities — used to validate the
    # checksum implementation against published, stable numbers.
    assert _afm_checksum_ok("094019245")  # OTE
    assert _afm_checksum_ok("094014201")  # National Bank of Greece
    assert _afm_checksum_ok("090027346")  # OPAP
    assert _afm_checksum_ok("094277965")  # Coca-Cola HBC Hellenic ops


def test_afm_checksum_rejects_invalid():
    assert not _afm_checksum_ok("123456789")
    assert not _afm_checksum_ok("000000001")


def test_normalize_afm_strips_prefix_and_validates():
    assert _normalize_afm("EL094019245") == "094019245"
    assert _normalize_afm("GR 094019245") == "094019245"
    assert _normalize_afm("094019245") == "094019245"


def test_normalize_afm_rejects_bad_input():
    with pytest.raises(InvalidIdentifierError):
        _normalize_afm("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_afm("EL123456789")  # bad checksum


def test_normalize_gemi_accepts_9_to_12_digits():
    assert _normalize_gemi("3823201000") == "3823201000"
    assert _normalize_gemi(" 1037501000 ") == "1037501000"
    with pytest.raises(InvalidIdentifierError):
        _normalize_gemi("12345")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_hits_live_endpoints():
    adapter = GRAdapter()
    health = await adapter.health_check()
    assert health.country_code == "GR"
    assert health.status.value in {"ok", "degraded", "error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_ote():
    adapter = GRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "EL094019245"
    )
    # VIES occasionally throttles or rate-limits; only assert structure when
    # we did get a response so the test is robust to upstream hiccups.
    if details is None:
        pytest.skip("VIES did not return a valid response for OTE ΑΦΜ.")
    assert details.country == "GR"
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches_for_opap():
    adapter = GRAdapter()
    matches = await adapter.search_by_name("OPAP", limit=5)
    # GEMI publicity portal availability is best-effort; if the endpoint
    # shape changed, the adapter returns [] rather than fabricating data.
    if not matches:
        pytest.skip("GEMI publicity portal returned no parseable matches.")
    assert all(m.country == "GR" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_gemi_opap():
    adapter = GRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "3823201000"
    )
    if details is None:
        pytest.skip("GEMI publicity portal did not return details for OPAP.")
    assert details.country == "GR"
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == "3823201000"
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_empty_list():
    adapter = GRAdapter()
    filings = await adapter.fetch_financials("3823201000")
    assert filings == []
