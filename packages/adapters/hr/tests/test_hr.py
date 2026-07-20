from __future__ import annotations

import os

import pytest

from packages.adapters._base.errors import (
    AdapterError,
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.hr import HRAdapter
from packages.adapters.hr.adapter import (
    _normalize_mbs,
    _normalize_oib,
    _oib_checksum_valid,
)
from packages.shared.models import AdapterStatus, IdentifierType

_HAS_CREDENTIALS = bool(
    os.getenv("HR_SUDREG_CLIENT_ID") and os.getenv("HR_SUDREG_CLIENT_SECRET")
)
requires_credentials = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="sudreg-data.gov.hr OAuth credentials not configured "
    "(HR_SUDREG_CLIENT_ID / HR_SUDREG_CLIENT_SECRET)",
)


def test_oib_checksum_known_valid():
    # INA, HEP, Pliva — real OIBs that must pass ISO 7064 MOD 11,10.
    for oib in ("27759560625", "28921978587", "41538015885"):
        assert _oib_checksum_valid(oib), oib


def test_oib_checksum_rejects_bad():
    assert not _oib_checksum_valid("27759560620")


def test_normalize_oib_strips_prefix():
    assert _normalize_oib("HR 27759560625") == "27759560625"


def test_normalize_oib_rejects_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_oib("12345")


def test_normalize_mbs_zero_pads():
    assert _normalize_mbs("80000604") == "080000604"
    assert _normalize_mbs("080000604") == "080000604"


@pytest.mark.asyncio
async def test_missing_credentials_raise_clear_error():
    if _HAS_CREDENTIALS:
        pytest.skip("credentials configured")
    adapter = HRAdapter()
    with pytest.raises(AdapterError, match="HR_SUDREG_CLIENT_ID"):
        await adapter.search_by_name("INA", limit=5)


@pytest.mark.asyncio
async def test_health_reports_blocked_without_credentials():
    if _HAS_CREDENTIALS:
        pytest.skip("credentials configured")
    health = await HRAdapter().health_check()
    assert health.status == AdapterStatus.BLOCKED
    assert health.requires_api_key and not health.api_key_present


@pytest.mark.asyncio
async def test_fetch_financials_not_implemented():
    adapter = HRAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.fetch_financials("27759560625", years=10)


@pytest.mark.asyncio
@pytest.mark.integration
@requires_credentials
async def test_search_finds_ina():
    adapter = HRAdapter()
    matches = await adapter.search_by_name("INA", limit=5)
    assert matches, "expected at least one match for INA"
    assert any("ina" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
@requires_credentials
async def test_lookup_ina_by_oib():
    adapter = HRAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "27759560625")
    assert details is not None
    assert details.country == "HR"
    assert any(i.value.endswith("27759560625") for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
@requires_credentials
async def test_lookup_ina_by_mbs():
    adapter = HRAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "080000604")
    assert details is not None
    assert details.country == "HR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_country():
    adapter = HRAdapter()
    health = await adapter.health_check()
    assert health.country_code == "HR"
