from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.at import ATAdapter
from packages.adapters.at.adapter import _normalize_fn, _normalize_uid
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_fn_accepts_variants():
    assert _normalize_fn("FN 81476 a") == "81476a"
    assert _normalize_fn("81476A") == "81476a"
    assert _normalize_fn("fn33209m") == "33209m"
    assert _normalize_fn("66209t") == "66209t"
    # FN may be present without a check letter on older entries.
    assert _normalize_fn("12345") == "12345"
    with pytest.raises(InvalidIdentifierError):
        _normalize_fn("ABCDE")
    with pytest.raises(InvalidIdentifierError):
        _normalize_fn("12345678901")


def test_normalize_uid_strips_at_prefix():
    assert _normalize_uid("ATU12832407") == "U12832407"
    assert _normalize_uid("atu 12832407") == "U12832407"
    assert _normalize_uid("U14660509") == "U14660509"
    # Bare 8 digits is also acceptable; we add the leading U.
    assert _normalize_uid("12832407") == "U12832407"
    with pytest.raises(InvalidIdentifierError):
        _normalize_uid("AT123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_uid("ATU1234567")  # 7 digits


@pytest.mark.asyncio
async def test_search_raises_not_implemented():
    adapter = ATAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("OMV")


@pytest.mark.asyncio
async def test_lookup_by_fn_raises_not_implemented():
    adapter = ATAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "FN 81476 a")


@pytest.mark.asyncio
async def test_lookup_by_fn_rejects_garbage_first():
    adapter = ATAdapter()
    # Invalid identifier should surface before the "not implemented" error
    # so callers debugging input get the precise message.
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "not-an-fn")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = ATAdapter()
    assert await adapter.fetch_financials("81476a") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = ATAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AT"
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)
    # Lookup is the only enabled capability free of charge.
    assert health.capabilities.get("lookup") is True
    assert health.capabilities.get("search") is False
    assert health.capabilities.get("financials") is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_via_vies_returns_record_or_none():
    """VIES must answer for AT VAT. The four published test UIDs may or may
    not currently validate (VIES can mark numbers invalid if the underlying
    registration changed), so the test only asserts on shape: either we get
    a CompanyDetails with a VAT identifier or we get None — never an
    exception, never invented data.
    """
    adapter = ATAdapter()
    for vat in ("ATU12832407", "ATU14660509", "ATU14809701", "ATU14624500"):
        details = await adapter.lookup_by_identifier(IdentifierType.VAT, vat)
        if details is None:
            continue
        assert details.country == "AT"
        vat_ids = [i for i in details.identifiers if i.type == IdentifierType.VAT]
        assert vat_ids, "VIES-validated record must carry the VAT identifier"
        assert vat_ids[0].value == vat.upper().replace(" ", "")
        # VIES for AT may redact name/address; if a name was returned it must
        # not be the literal privacy placeholder.
        assert details.name and details.name != "---"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_invalid_uid_returns_none():
    adapter = ATAdapter()
    # Well-formed but unallocated AT UID — VIES should answer "valid=false".
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "ATU00000000")
    assert details is None
