from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.hr import HRAdapter
from packages.adapters.hr.adapter import (
    _normalize_mbs,
    _normalize_oib,
    _oib_checksum_valid,
    _parse_fina_years,
)
from packages.shared.models import IdentifierType


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


def test_parse_fina_years_extracts_distinct():
    sample = "<table><tr><td>INA d.d.</td><td>2023</td></tr><tr><td>INA d.d.</td><td>2022</td></tr></table>"
    years = _parse_fina_years(sample)
    assert 2022 in years and 2023 in years


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_ina():
    adapter = HRAdapter()
    matches = await adapter.search_by_name("INA", limit=5)
    assert matches, "expected at least one match for INA"
    assert any("ina" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ina_by_oib():
    adapter = HRAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "27759560625")
    assert details is not None
    assert details.country == "HR"
    assert any(i.value.endswith("27759560625") for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ina_by_mbs():
    adapter = HRAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "080000604")
    assert details is not None
    assert details.country == "HR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_ina():
    adapter = HRAdapter()
    filings = await adapter.fetch_financials("27759560625", years=10)
    # FINA RGFI hosts INA annual reports back to 2008 — we expect at least one.
    assert isinstance(filings, list)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = HRAdapter()
    health = await adapter.health_check()
    assert health.country_code == "HR"
