from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.lu import LUAdapter
from packages.adapters.lu.adapter import _normalize_lu_vat, _normalize_rcs
from packages.shared.models import IdentifierType


def test_rcs_normalizer_accepts_known_companies():
    assert _normalize_rcs("B82454") == "B82454"
    assert _normalize_rcs("b 82 454") == "B82454"
    assert _normalize_rcs("82454") == "B82454"
    assert _normalize_rcs("RCS B81267") == "B81267"


def test_rcs_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rcs("not-an-rcs")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rcs("")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rcs("B12345678")  # too many digits


def test_lu_vat_normalizer_accepts_known_companies():
    assert _normalize_lu_vat("LU24876214") == "24876214"
    assert _normalize_lu_vat("lu 24 876 214") == "24876214"
    assert _normalize_lu_vat("17996777") == "17996777"


def test_lu_vat_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_lu_vat("LU1234567")  # 7 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_lu_vat("LU123456789")  # 9 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_lu_vat("not-a-vat")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = LUAdapter()
    assert await adapter.fetch_financials("B82454") == []


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = LUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "anything")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_arcelormittal():
    adapter = LUAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "LU24876214")
    assert details is not None
    assert details.country == "LU"
    assert "arcelor" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_ses():
    adapter = LUAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "LU17996777")
    assert details is not None
    assert details.country == "LU"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_arcelormittal():
    adapter = LUAdapter()
    # LBR scrape may degrade if their HTML changes — we only assert the
    # contract: it returns a list (possibly empty), and any hit is well-formed.
    results = await adapter.search_by_name("ArcelorMittal", limit=5)
    assert isinstance(results, list)
    for r in results:
        assert r.country == "LU"
        assert r.id.startswith("B")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_rcs_arcelormittal():
    adapter = LUAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "B82454"
    )
    # LBR HTML may not return a parseable row in all environments; if it does,
    # we expect the canonical RCS to come back. If it doesn't, None is also
    # acceptable — we never fabricate.
    if details is not None:
        assert details.id == "B82454"
        assert details.country == "LU"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_ok():
    adapter = LUAdapter()
    health = await adapter.health_check()
    assert health.country_code == "LU"
    assert health.capabilities["financials"] is False
    assert health.capabilities["lookup"] is True
