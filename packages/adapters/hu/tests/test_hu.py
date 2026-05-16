from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.hu import HUAdapter
from packages.adapters.hu.adapter import (
    _normalize_cegjegyzekszam,
    _normalize_hu_vat,
)
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_cegjegyzekszam_dashed():
    assert _normalize_cegjegyzekszam("01-10-041585") == "01-10-041585"


def test_normalize_cegjegyzekszam_undashed():
    assert _normalize_cegjegyzekszam("0110041585") == "01-10-041585"


def test_normalize_cegjegyzekszam_rejects_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_cegjegyzekszam("01-10-04158")


def test_normalize_hu_vat_strips_prefix():
    assert _normalize_hu_vat("HU10537914") == "10537914"


def test_normalize_hu_vat_from_adoszam():
    assert _normalize_hu_vat("10537914-4-44") == "10537914"


def test_normalize_hu_vat_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_hu_vat("HU1234567")


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = HUAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("OTP Bank")


@pytest.mark.asyncio
async def test_lookup_by_cegjegyzekszam_returns_deeplink():
    adapter = HUAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "01-10-041585"
    )
    assert details is not None
    assert details.id == "01-10-041585"
    assert details.country == "HU"
    assert details.source_url and "e-beszamolo.im.gov.hu" in details.source_url
    assert details.identifiers[0].type == IdentifierType.COMPANY_NUMBER


@pytest.mark.asyncio
async def test_fetch_financials_empty_without_browser():
    adapter = HUAdapter()
    # MVP returns no structured filings — e-beszamolo needs a browser session.
    filings = await adapter.fetch_financials("01-10-041585")
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live_vies():
    adapter = HUAdapter()
    health = await adapter.health_check()
    assert health.country_code == "HU"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED}
    assert health.capabilities.get("lookup") is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_otp_bank_by_vat():
    adapter = HUAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "HU10537914")
    assert details is not None
    assert details.country == "HU"
    # VIES returns the legal name for valid HU registrations.
    assert "OTP" in details.name.upper()
    assert any(
        i.type == IdentifierType.VAT and i.value == "HU10537914"
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_mol_by_vat():
    adapter = HUAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "HU10625790")
    assert details is not None
    assert "MOL" in details.name.upper()
