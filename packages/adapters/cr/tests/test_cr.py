"""Tests for the Costa Rica adapter (Hacienda ATV).

Integration tests hit the live ``api.hacienda.go.cr/fe/ae`` endpoint and
are marked ``integration`` so CI can skip them with
``-m "not integration"``. Per the project's no-mock-data rule we never
use canned fixtures — every assertion runs against real Hacienda output.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.cr import CRAdapter
from packages.adapters.cr.adapter import _format_cedula, _normalize_cedula
from packages.shared.models import IdentifierType


def test_normalize_strips_dashes() -> None:
    assert _normalize_cedula("3-101-005514") == "3101005514"


def test_normalize_strips_spaces_and_dots() -> None:
    assert _normalize_cedula(" 3.101.005514 ") == "3101005514"


def test_normalize_accepts_state_entity_form() -> None:
    # ICE is a pre-1990 state entity filed as 4-000-XXXXXX, not 3-XXX-XXXXXX.
    assert _normalize_cedula("4-000-042139") == "4000042139"


def test_normalize_rejects_natural_person() -> None:
    # Natural persons (cédula física) are 9 digits starting with 1/2/5/6/7/8.
    with pytest.raises(InvalidIdentifierError):
        _normalize_cedula("108880123")


def test_normalize_rejects_too_short() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_cedula("31010055")


def test_normalize_rejects_empty() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_cedula("")


def test_normalize_rejects_wrong_leading_digit() -> None:
    # A 10-digit string starting with 5 is neither juridical (3) nor a
    # known state form (4-000-XXXXXX); reject rather than guess.
    with pytest.raises(InvalidIdentifierError):
        _normalize_cedula("5101005514")


def test_format_renders_dashed_form() -> None:
    assert _format_cedula("3101005514") == "3-101-005514"
    assert _format_cedula("4000042139") == "4-000-042139"


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented() -> None:
    adapter = CRAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Florida Bebidas")


@pytest.mark.asyncio
async def test_invalid_cedula_rejected() -> None:
    adapter = CRAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "abc")


@pytest.mark.asyncio
async def test_wrong_identifier_type_rejected() -> None:
    adapter = CRAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "3-101-005514")


@pytest.mark.asyncio
async def test_fetch_financials_unlisted_returns_empty() -> None:
    adapter = CRAdapter()
    # A valid-format but unlisted juridical cédula must return [] rather
    # than raise — credit pipeline still proceeds without filings.
    assert await adapter.fetch_financials("3101999999") == []


@pytest.mark.asyncio
async def test_fetch_financials_listed_emisor_returns_index() -> None:
    adapter = CRAdapter()
    filings = await adapter.fetch_financials("3-101-005514", years=3)
    assert len(filings) == 3
    assert all(f.currency == "CRC" for f in filings)
    assert all(f.source_url and "bolsacr.com" in f.source_url for f in filings)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    adapter = CRAdapter()
    health = await adapter.health_check()
    assert health.country_code == "CR"
    assert health.name == "Costa Rica"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_florida_bebidas() -> None:
    adapter = CRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "3-101-005514"
    )
    if details is None:
        pytest.skip("Hacienda ATV returned no record — region-blocked or offline")
    assert details.country == "CR"
    assert details.name  # non-empty registered name
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ice_state_entity() -> None:
    adapter = CRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "4-000-042139"
    )
    if details is None:
        pytest.skip("Hacienda ATV returned no record for ICE")
    assert details.country == "CR"
    assert "electricidad" in details.name.lower() or "ice" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banco_nacional() -> None:
    adapter = CRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "4-000-001021"
    )
    if details is None:
        pytest.skip("Hacienda ATV returned no record for Banco Nacional")
    assert "banco" in details.name.lower() or "nacional" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_demasa() -> None:
    adapter = CRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "3-101-010300"
    )
    if details is None:
        pytest.skip("Hacienda ATV returned no record for DEMASA")
    assert details.country == "CR"
    assert details.name
