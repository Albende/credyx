from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.bg import BGAdapter
from packages.shared.models import (
    AdapterStatus,
    FilingType,
    IdentifierType,
)


def test_normalize_strips_bg_prefix_and_validates():
    from packages.adapters.bg.adapter import _normalize_eik

    assert _normalize_eik(" BG 831902088 ") == "831902088"
    assert _normalize_eik("8319020880001") == "8319020880001"  # 13-digit branch
    with pytest.raises(InvalidIdentifierError):
        _normalize_eik("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_eik("ABCDEFGHI")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_real_matches():
    adapter = BGAdapter()
    matches = await adapter.search_by_name("Софарма", limit=5)
    assert matches, "expected name-search matches for Софарма"
    eiks = {m.id for m in matches}
    assert "831902088" in eiks  # Sopharma AD is the exact-name hit
    for m in matches:
        assert m.country == "BG"
        assert m.id.isdigit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = BGAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BG"
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)
    assert health.capabilities.get("lookup") is True
    assert health.capabilities.get("search") is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_sopharma_by_eik():
    adapter = BGAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "831902088"
    )
    assert details is not None
    assert details.country == "BG"
    # The registry returns the Cyrillic spelling.
    assert "СОФАРМА" in details.name.upper() or "SOPHARMA" in details.name.upper()
    eik_ids = [i for i in details.identifiers if i.type == IdentifierType.COMPANY_NUMBER]
    assert eik_ids and eik_ids[0].value == "831902088"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_resolves_same_company():
    adapter = BGAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "BG831902088")
    assert details is not None
    assert details.id == "831902088"
    vat_ids = [i for i in details.identifiers if i.type == IdentifierType.VAT]
    # VIES may be transiently unavailable; if it answered, the VAT must match.
    if vat_ids:
        assert vat_ids[0].value == "BG831902088"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_eik_returns_none():
    adapter = BGAdapter()
    # Valid checksum-shape but unallocated 9-digit number.
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "000000001"
    )
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_annual_reports():
    adapter = BGAdapter()
    filings = await adapter.fetch_financials("831902088", years=20)
    # Sopharma is a major listed JSC, so the Announced Acts section reliably
    # contains at least one filed annual financial report.
    assert isinstance(filings, list)
    annual = [f for f in filings if f.type == FilingType.ANNUAL_REPORT]
    assert annual, "expected at least one annual financial report for Sopharma"
    for f in annual:
        assert f.company_id == "831902088"
        assert f.currency == "BGN"
        assert f.document_format == "pdf"
        assert f.document_url and "/CR/api/Documents/" in f.document_url
