"""Tests for the UAE adapter.

Unit tests cover TRN normalization and the "no mock data" contract.
The DFM/ADX health probe is marked `integration` because it hits real
public homepages.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.ae import AEAdapter
from packages.adapters.ae.adapter import normalize_trn
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_trn_strips_spaces_and_ae_prefix():
    assert normalize_trn("100 1234 5678 9003") == "100123456789003"
    assert normalize_trn("AE100123456789003") == "100123456789003"
    assert normalize_trn("ae-100-123456789003") == "100123456789003"


def test_normalize_trn_rejects_short():
    with pytest.raises(InvalidIdentifierError):
        normalize_trn("12345")


def test_normalize_trn_rejects_non_numeric():
    with pytest.raises(InvalidIdentifierError):
        normalize_trn("ABCDEFGHIJKLMNO")


def test_metadata():
    adapter = AEAdapter()
    assert adapter.country_code == "AE"
    assert adapter.primary_identifier == IdentifierType.VAT
    assert IdentifierType.VAT in adapter.identifier_types
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    with pytest.raises(AdapterNotImplementedError):
        await AEAdapter().search_by_name("Emaar Properties PJSC")


@pytest.mark.asyncio
async def test_lookup_by_trn_validates_then_raises_not_implemented():
    adapter = AEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "100123456789003")


@pytest.mark.asyncio
async def test_lookup_by_trn_rejects_bad_format():
    adapter = AEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123")


@pytest.mark.asyncio
async def test_lookup_by_trade_licence_raises_not_implemented():
    adapter = AEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "DED-12345-2024"
        )


@pytest.mark.asyncio
async def test_lookup_empty_company_number_rejected():
    adapter = AEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "  ")


@pytest.mark.asyncio
async def test_lookup_unsupported_identifier_type():
    adapter = AEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "529900T8BM49AURSDO55")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_list_not_mock():
    # Etisalat e& on DFM — until the browser pool lands we return [], not
    # a fabricated filing list.
    filings = await AEAdapter().fetch_financials("ETISALAT", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_dfm_or_adx():
    health = await AEAdapter().health_check()
    assert health.country_code == "AE"
    # Adapter is intentionally blocked (no free public APIs); we should
    # never claim OK.
    assert health.status in {AdapterStatus.BLOCKED, AdapterStatus.ERROR}
    assert health.capabilities == {
        "search": False,
        "lookup": False,
        "financials": False,
    }
