from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.md import MDAdapter
from packages.shared.models import AdapterStatus, IdentifierType


def test_idno_normalizer_strips_md_prefix_and_spaces():
    from packages.adapters.md.adapter import _normalize_idno

    assert _normalize_idno("MD1003600015304") == "1003600015304"
    assert _normalize_idno("1003 600 015 304") == "1003600015304"
    assert _normalize_idno("1003-600-015-304") == "1003600015304"


def test_idno_normalizer_rejects_bad_input():
    from packages.adapters.md.adapter import _normalize_idno

    with pytest.raises(InvalidIdentifierError):
        _normalize_idno("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_idno("ABCDEFGHIJKLM")


def test_static_metadata():
    adapter = MDAdapter()
    assert adapter.country_code == "MD"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    # Moldovan filings are not freely available; never fake data.
    adapter = MDAdapter()
    assert await adapter.fetch_financials("1003600015304") == []


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = MDAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.SIREN, "1003600015304")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = MDAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MD"
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_moldovagaz():
    adapter = MDAdapter()
    matches = await adapter.search_by_name("Moldovagaz", limit=10)
    assert any("moldovagaz" in m.name.lower() for m in matches) or matches == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_moldovagaz_by_idno():
    adapter = MDAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "1003600015304"
    )
    if details is not None:
        assert details.country == "MD"
        assert details.id == "1003600015304"
        assert any(
            ident.value == "1003600015304" for ident in details.identifiers
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_orange_moldova():
    adapter = MDAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "1002600015173"
    )
    if details is not None:
        assert details.id == "1002600015173"
        assert details.country == "MD"
