from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ro import ROAdapter
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_cui_strips_ro_prefix():
    from packages.adapters.ro.adapter import _normalize_cui

    assert _normalize_cui("RO1590082") == 1590082
    assert _normalize_cui(" 1590082 ") == 1590082
    assert _normalize_cui("ro 5022670") == 5022670


def test_normalize_cui_rejects_garbage():
    from packages.adapters.ro.adapter import _normalize_cui

    with pytest.raises(InvalidIdentifierError):
        _normalize_cui("ABC")
    with pytest.raises(InvalidIdentifierError):
        _normalize_cui("1")  # too short
    with pytest.raises(InvalidIdentifierError):
        _normalize_cui("12345678901")  # too long


@pytest.mark.asyncio
async def test_search_by_name_is_unsupported():
    adapter = ROAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Petrom", limit=5)


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = ROAdapter()
    assert await adapter.fetch_financials("1590082") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_anaf_live():
    adapter = ROAdapter()
    health = await adapter.health_check()
    assert health.status == AdapterStatus.OK
    assert health.capabilities["lookup"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_omv_petrom():
    adapter = ROAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "RO1590082")
    assert details is not None
    assert details.id == "1590082"
    assert "petrom" in details.name.lower()
    assert details.country == "RO"
    # VAT-registered, so we should expose both the CUI and the VAT id.
    types = {i.type for i in details.identifiers}
    assert IdentifierType.COMPANY_NUMBER in types


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banca_transilvania():
    adapter = ROAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "5022670"
    )
    assert details is not None
    assert "transilvania" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_hidroelectrica():
    adapter = ROAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "13267213"
    )
    assert details is not None
    assert "hidroelectrica" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_cui_returns_none():
    adapter = ROAdapter()
    # 99 is not a real CUI — ANAF should return notFound.
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "99")
    assert details is None
