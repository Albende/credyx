from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.py import PYAdapter
from packages.adapters.py.adapter import _normalize_ruc
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_ruc_accepts_hyphenated():
    assert _normalize_ruc("80012345-6") == "80012345-6"


def test_normalize_ruc_accepts_unhyphenated_and_inserts_dash():
    assert _normalize_ruc("800123456") == "80012345-6"


def test_normalize_ruc_rejects_letters():
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("ABC12345-6")


def test_normalize_ruc_rejects_too_long():
    with pytest.raises(InvalidIdentifierError):
        _normalize_ruc("123456789-0")


def test_adapter_metadata():
    adapter = PYAdapter()
    assert adapter.country_code == "PY"
    assert adapter.country_name == "Paraguay"
    assert IdentifierType.VAT in adapter.identifier_types
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.primary_identifier == IdentifierType.VAT
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = PYAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Cervepar")


@pytest.mark.asyncio
async def test_lookup_by_identifier_raises_not_implemented_for_valid_ruc():
    adapter = PYAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "80012345-6")


@pytest.mark.asyncio
async def test_lookup_by_identifier_rejects_invalid_ruc():
    adapter = PYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "not-a-ruc")


@pytest.mark.asyncio
async def test_lookup_by_identifier_rejects_wrong_id_type():
    adapter = PYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "80012345-6")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = PYAdapter()
    assert await adapter.fetch_financials("80012345-6") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_bvpasa():
    adapter = PYAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PY"
    assert health.status in {AdapterStatus.DEGRADED, AdapterStatus.ERROR}
    assert health.capabilities == {
        "search": False,
        "lookup": False,
        "financials": False,
    }
