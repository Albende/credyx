from __future__ import annotations

import asyncio

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.de import DEAdapter
from packages.shared.models import AdapterStatus, IdentifierType


# OffeneRegister.de shut its free API down (2026); the adapter is disabled
# until a free live source exists. See docs/countries/de.md.


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_disabled():
    adapter = DEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "DE"
    assert health.status in (AdapterStatus.NOT_IMPLEMENTED, AdapterStatus.DEGRADED)
    assert health.capabilities == {
        "search": False,
        "lookup": False,
        "financials": False,
    }


def test_search_raises_not_implemented():
    adapter = DEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        asyncio.run(adapter.search_by_name("Siemens", limit=10))


def test_lookup_accepts_plain_hrb_number():
    adapter = DEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        asyncio.run(adapter.lookup_by_identifier(IdentifierType.HRB, "42243"))


def test_lookup_accepts_prefixed_hrb_with_court():
    adapter = DEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        asyncio.run(
            adapter.lookup_by_identifier(IdentifierType.HRB, "HRB 42243 München")
        )


def test_lookup_accepts_valid_vat():
    adapter = DEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        asyncio.run(adapter.lookup_by_identifier(IdentifierType.VAT, "DE129273398"))


def test_fetch_financials_raises_not_implemented():
    adapter = DEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        asyncio.run(adapter.fetch_financials("siemens_ag", years=3))


def test_invalid_vat_format_rejected():
    adapter = DEAdapter()
    with pytest.raises(InvalidIdentifierError):
        asyncio.run(adapter.lookup_by_identifier(IdentifierType.VAT, "FR12345678901"))


def test_invalid_hrb_format_rejected():
    adapter = DEAdapter()
    with pytest.raises(InvalidIdentifierError):
        asyncio.run(adapter.lookup_by_identifier(IdentifierType.HRB, "garbage 999"))


def test_unsupported_identifier_rejected():
    adapter = DEAdapter()
    with pytest.raises(InvalidIdentifierError):
        asyncio.run(adapter.lookup_by_identifier(IdentifierType.SIREN, "123456789"))
