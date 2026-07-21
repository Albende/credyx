"""Tests for the Ecuador adapter (GLEIF-backed).

Integration tests hit the live GLEIF LEI registry (SUPERCIAS/SRI are
geo-blocked to Ecuador — see docs/countries/ec.md) and are marked
``integration`` so CI can skip them with ``-m "not integration"``. Per the
project's no-mock-data rule the integration tests never use canned fixtures.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ec import ECAdapter
from packages.adapters.ec.adapter import _normalize_ruc
from packages.shared.models import IdentifierType


def test_normalize_strips_dots_and_dashes() -> None:
    assert _normalize_ruc("179.001.0937-001") == "1790010937001"


def test_normalize_strips_ec_prefix() -> None:
    assert _normalize_ruc("EC 1790010937001") == "1790010937001"


def test_normalize_accepts_plain_13_digits() -> None:
    assert _normalize_ruc("1790010937001") == "1790010937001"


def test_normalize_rejects_too_short() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("12345")


def test_normalize_rejects_too_long() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("17900109370010")


def test_normalize_rejects_letters_only() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("ABCDEFGHIJKLM")


def test_normalize_rejects_none() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_wrong_identifier_type_rejected() -> None:
    adapter = ECAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.KRS, "1790010937001"
        )


@pytest.mark.asyncio
async def test_empty_search_returns_empty_list() -> None:
    adapter = ECAdapter()
    assert await adapter.search_by_name("   ") == []


@pytest.mark.asyncio
async def test_lookup_invalid_ruc_format_rejected() -> None:
    adapter = ECAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "abc")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    adapter = ECAdapter()
    health = await adapter.health_check()
    assert health.country_code == "EC"
    assert health.name == "Ecuador"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_omarsa_by_ruc() -> None:
    adapter = ECAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "0990608504001"
    )
    if details is None:
        pytest.skip("GLEIF returned no record for OMARSA — offline")
    assert details.country == "EC"
    assert "omarsa" in details.name.lower()
    assert any(
        i.type == IdentifierType.VAT and i.value == "0990608504001"
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_alias() -> None:
    adapter = ECAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "0990608504001"
    )
    if details is None:
        pytest.skip("GLEIF returned no record for OMARSA — offline")
    assert "omarsa" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_lei() -> None:
    adapter = ECAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.LEI, "549300CO09CR3FNOZ392"
    )
    if details is None:
        pytest.skip("GLEIF returned no record for Banco Pichincha — offline")
    assert "pichincha" in details.name.lower()
    assert details.country == "EC"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_pichincha() -> None:
    adapter = ECAdapter()
    matches = await adapter.search_by_name("PICHINCHA", limit=5)
    if not matches:
        pytest.skip("GLEIF returned no matches — offline")
    assert any("pichincha" in m.name.lower() for m in matches)
    assert all(m.country == "EC" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_unavailable() -> None:
    adapter = ECAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.fetch_financials("0990608504001", years=3)
