from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.at import ATAdapter
from packages.adapters.at.adapter import _normalize_fn, _normalize_uid
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


def test_normalize_fn_accepts_variants():
    assert _normalize_fn("FN 93363 z") == "93363z"
    assert _normalize_fn("93363Z") == "93363z"
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
async def test_lookup_rejects_garbage_fn():
    adapter = ATAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "not-an-fn")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = ATAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "irrelevant")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = ATAdapter()
    health = await adapter.health_check()
    assert health.country_code == "AT"
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)
    assert health.capabilities.get("search") is True
    assert health.capabilities.get("lookup") is True
    assert health.capabilities.get("financials") is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_live():
    adapter = ATAdapter()
    matches = await adapter.search_by_name("voestalpine", limit=5)
    assert matches, "JustizOnline must return matches for a real company name"
    top = matches[0]
    assert top.country == "AT"
    assert top.id  # canonical Firmenbuchnummer
    assert any(i.type == IdentifierType.COMPANY_NUMBER for i in top.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_fn_live():
    adapter = ATAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "93363z"
    )
    assert details is not None
    assert details.country == "AT"
    assert "OMV" in details.name
    assert details.registered_address
    fn_ids = [i for i in details.identifiers if i.type == IdentifierType.COMPANY_NUMBER]
    assert fn_ids and fn_ids[0].value == "93363z"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_live():
    adapter = ATAdapter()
    filings = await adapter.fetch_financials("93363z", years=3)
    assert filings, "OMV is a listed issuer with ESEF filings"
    assert len(filings) <= 3
    for f in filings:
        assert f.type == FilingType.ANNUAL_REPORT
        assert f.currency == "EUR"
        assert f.document_url and f.document_url.startswith("https://filings.xbrl.org/")
        assert f.period_end is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_unlisted_returns_empty():
    adapter = ATAdapter()
    # Well-formed FN unlikely to map to an LEI-holding listed issuer.
    assert await adapter.fetch_financials("1a") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_via_vies_returns_record_or_none():
    """VIES must answer for AT VAT. Published test UIDs may or may not validate
    at any moment; assert only on shape — a CompanyDetails with a VAT identifier
    or None, never an exception, never invented data.
    """
    adapter = ATAdapter()
    for vat in ("ATU12832407", "ATU14660509", "ATU14809701", "ATU14624500"):
        details = await adapter.lookup_by_identifier(IdentifierType.VAT, vat)
        if details is None:
            continue
        assert details.country == "AT"
        vat_ids = [i for i in details.identifiers if i.type == IdentifierType.VAT]
        assert vat_ids, "VIES-validated record must carry the VAT identifier"
        assert details.name and details.name != "---"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_invalid_uid_returns_none():
    adapter = ATAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "ATU00000000")
    assert details is None
