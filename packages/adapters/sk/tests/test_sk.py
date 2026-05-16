"""Integration tests for the Slovakia adapter.

These tests hit the real public ORSR (orsr.sk) and RÚZ (registeruz.sk)
endpoints. Marked `integration` so CI can opt-out with `-m "not integration"`.

Test companies (large, long-lived, listed in docs/countries/sk.md):
- Volkswagen Slovakia, a.s. — IČO 35757442
- Slovenské elektrárne, a.s. — IČO 35829052
- Tatra banka, a.s.        — IČO 00686930
- Slovnaft, a.s.            — IČO 31322832
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.sk import SKAdapter
from packages.adapters.sk.adapter import _normalize_ico, _normalize_vat
from packages.shared.models import IdentifierType


def test_normalize_ico_pads_short():
    assert _normalize_ico("686930") == "00686930"
    assert _normalize_ico("00686930") == "00686930"
    assert _normalize_ico("  35 757 442 ") == "35757442"


def test_normalize_ico_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_ico("abc")
    with pytest.raises(InvalidIdentifierError):
        _normalize_ico("123456789")  # 9 digits


def test_normalize_vat_strips_sk_prefix():
    assert _normalize_vat("SK2020220862") == "2020220862"
    assert _normalize_vat("2020220862") == "2020220862"
    assert _normalize_vat(" sk 2020220862 ") == "2020220862"


def test_normalize_vat_rejects_wrong_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("SK202022086")  # 9 digits


def test_adapter_metadata():
    a = SKAdapter()
    assert a.country_code == "SK"
    assert a.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.VAT in a.identifier_types
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_orsr():
    a = SKAdapter()
    health = await a.health_check()
    assert health.country_code == "SK"
    assert health.status.value in ("ok", "error")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_slovnaft():
    a = SKAdapter()
    matches = await a.search_by_name("Slovnaft", limit=10)
    assert matches, "expected ORSR to return at least one Slovnaft result"
    assert any("slovnaft" in m.name.lower() for m in matches)
    main = next((m for m in matches if m.name.strip().upper().startswith("SLOVNAFT, A.S")), None)
    assert main is not None
    assert main.country == "SK"
    assert main.source_url and "vypis.asp" in main.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_ico_volkswagen():
    a = SKAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "35757442")
    assert details is not None
    assert "volkswagen" in details.name.lower()
    assert details.country == "SK"
    id_types = {i.type for i in details.identifiers}
    assert IdentifierType.COMPANY_NUMBER in id_types
    assert IdentifierType.VAT in id_types
    vat = next(i for i in details.identifiers if i.type == IdentifierType.VAT)
    assert vat.value.startswith("SK") and len(vat.value) == 12
    assert details.legal_form  # mapped from pravnaForma=121
    assert details.registered_address
    assert details.incorporation_date is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_ico_tatra_banka_zero_padded():
    a = SKAdapter()
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "00686930")
    assert details is not None
    assert "tatra" in details.name.lower()
    assert details.id == "00686930"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_volkswagen():
    a = SKAdapter()
    details = await a.lookup_by_identifier(IdentifierType.VAT, "SK2020220862")
    assert details is not None
    assert "volkswagen" in details.name.lower()
    assert details.id == "35757442"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_unknown_returns_none():
    a = SKAdapter()
    # 10000001 is in the valid 8-digit range but is not assigned to any
    # accounting unit in RÚZ — confirmed by an empty `id` array. Codes
    # like 99999999 are real sole-proprietor IČOs and would return data.
    details = await a.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, "10000001")
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_volkswagen_returns_pdfs():
    a = SKAdapter()
    filings = await a.fetch_financials("35757442", years=5)
    assert filings, "RÚZ should return at least one recent annual filing for VW Slovakia"
    f = filings[0]
    assert f.currency == "EUR"
    assert f.document_format == "pdf"
    assert f.document_url and f.document_url.startswith(
        "https://www.registeruz.sk/cruz-public/domain/financialreport/pdf/"
    )
    # Newest filing should be within the requested window.
    from datetime import datetime
    cutoff = datetime.utcnow().year - 5
    assert f.year >= cutoff


def test_lookup_rejects_unsupported_identifier():
    import asyncio

    a = SKAdapter()
    with pytest.raises(InvalidIdentifierError):
        asyncio.run(a.lookup_by_identifier(IdentifierType.LEI, "1234"))
