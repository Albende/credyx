from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ar import ARAdapter
from packages.adapters.ar.adapter import _normalize_cuit
from packages.shared.models import IdentifierType


def test_normalize_cuit_accepts_formatted():
    assert _normalize_cuit("30-54668997-9") == "30546689979"
    assert _normalize_cuit("30546689979") == "30546689979"
    assert _normalize_cuit(" 30 54668997 9 ") == "30546689979"


def test_normalize_cuit_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_cuit("12345")


def test_normalize_cuit_rejects_bad_checksum():
    with pytest.raises(InvalidIdentifierError):
        _normalize_cuit("30546689971")


@pytest.mark.asyncio
async def test_search_by_name_is_unimplemented():
    adapter = ARAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("YPF")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ypf():
    adapter = ARAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "30-54668997-9")
    assert details is not None
    assert "ypf" in details.name.lower()
    assert details.country == "AR"
    assert any(i.value == "30546689979" for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banco_macro():
    adapter = ARAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "30-50001008-4"
    )
    assert details is not None
    assert "macro" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_empty_for_non_listed():
    adapter = ARAdapter()
    filings = await adapter.fetch_financials("30703088534")
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = ARAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AR"
    assert health.capabilities["lookup"] is True
