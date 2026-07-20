from __future__ import annotations

import base64
import hashlib
import json

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.hu import HUAdapter
from packages.adapters.hu.adapter import (
    _normalize_cegjegyzekszam,
    _normalize_hu_vat,
    _solve_altcha,
)
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


def test_normalize_cegjegyzekszam_dashed():
    assert _normalize_cegjegyzekszam("01-10-041585") == "01-10-041585"


def test_normalize_cegjegyzekszam_undashed():
    assert _normalize_cegjegyzekszam("0110041585") == "01-10-041585"


def test_normalize_cegjegyzekszam_rejects_short():
    with pytest.raises(InvalidIdentifierError):
        _normalize_cegjegyzekszam("01-10-04158")


def test_normalize_hu_vat_strips_prefix():
    assert _normalize_hu_vat("HU10484878") == "10484878"


def test_normalize_hu_vat_from_adoszam():
    assert _normalize_hu_vat("10484878-2-44") == "10484878"


def test_normalize_hu_vat_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_hu_vat("HU1234567")


def test_solve_altcha_finds_number():
    salt, number = "deadbeef", 4321
    challenge = {
        "algorithm": "SHA-256",
        "salt": salt,
        "challenge": hashlib.sha256(f"{salt}{number}".encode()).hexdigest(),
        "signature": "sig",
        "maxnumber": 10000,
    }
    payload = json.loads(base64.b64decode(_solve_altcha(challenge)))
    assert payload["number"] == number
    assert payload["salt"] == salt


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_live():
    adapter = HUAdapter()
    matches = await adapter.search_by_name("OTP Bank")
    assert matches
    assert any(m.id == "01-10-041585" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_cegjegyzekszam_live():
    adapter = HUAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "01-10-041585"
    )
    assert details is not None
    assert details.id == "01-10-041585"
    assert details.country == "HU"
    assert "OTP" in details.name.upper()
    assert details.identifiers[0].type == IdentifierType.COMPANY_NUMBER


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_live():
    adapter = HUAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "HU10484878")
    assert details is not None
    assert "RICHTER" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_live():
    adapter = HUAdapter()
    filings = await adapter.fetch_financials("01-10-041585", years=3)
    assert filings
    assert all(f.type == FilingType.ANNUAL_REPORT for f in filings)
    assert all(f.period_end is not None for f in filings)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = HUAdapter()
    health = await adapter.health_check()
    assert health.country_code == "HU"
    assert health.status in {AdapterStatus.OK, AdapterStatus.DEGRADED}
    assert health.capabilities.get("financials") is True
