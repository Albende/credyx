from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    BlockedByRegistryError,
    InvalidIdentifierError,
)
from packages.adapters.mx import MXAdapter
from packages.adapters.mx.adapter import _normalize_rfc
from packages.shared.models import AdapterStatus, IdentifierType


def test_rfc_normalizer_accepts_known_companies():
    # Real test RFCs from CLAUDE.md / SAT public records.
    assert _normalize_rfc("PEP970814I20") == "PEP970814I20"
    assert _normalize_rfc("amx010120cka") == "AMX010120CKA"
    assert _normalize_rfc(" BIM660325IT8 ") == "BIM660325IT8"
    assert _normalize_rfc("WME-970924-4W4") == "WME9709244W4"


def test_rfc_normalizer_rejects_persona_fisica():
    with pytest.raises(InvalidIdentifierError, match="persona física"):
        _normalize_rfc("VECJ880326XXX")


def test_rfc_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rfc("NOT-A-RFC")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rfc("PEP97AB14I20")


@pytest.mark.asyncio
async def test_search_by_name_is_not_implemented():
    adapter = MXAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Pemex")


@pytest.mark.asyncio
async def test_lookup_invalid_identifier_type():
    adapter = MXAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "PEP970814I20")


@pytest.mark.asyncio
async def test_lookup_known_rfc_is_blocked_by_captcha():
    adapter = MXAdapter()
    with pytest.raises(BlockedByRegistryError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "PEP970814I20")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_valid_rfc():
    adapter = MXAdapter()
    filings = await adapter.fetch_financials("AMX010120CKA")
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_validates_rfc():
    adapter = MXAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("garbage")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_sat():
    adapter = MXAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MX"
    # SAT may be reachable (DEGRADED — no API) or unreachable (ERROR). Either
    # way the adapter must not pretend to be OK.
    assert health.status in (AdapterStatus.DEGRADED, AdapterStatus.ERROR)
    assert health.capabilities == {"search": False, "lookup": False, "financials": False}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_integration_pemex_lookup_surfaces_block():
    # Real RFC for Petróleos Mexicanos. We expect a clean BlockedByRegistryError
    # rather than a fabricated CompanyDetails — non-negotiable rule #1.
    adapter = MXAdapter()
    with pytest.raises(BlockedByRegistryError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "PEP970814I20")
