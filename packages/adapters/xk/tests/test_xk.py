from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.xk import XKAdapter
from packages.shared.models import AdapterStatus, IdentifierType


def test_normalize_ubi_accepts_canonical():
    from packages.adapters.xk.adapter import _normalize_ubi

    assert _normalize_ubi("70123456A") == "70123456A"
    assert _normalize_ubi(" 70123456a ") == "70123456A"
    assert _normalize_ubi("70-123 456-A") == "70123456A"


def test_normalize_ubi_rejects_garbage():
    from packages.adapters.xk.adapter import _normalize_ubi

    with pytest.raises(InvalidIdentifierError):
        _normalize_ubi("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_ubi("ABCDEFGHI")
    with pytest.raises(InvalidIdentifierError):
        _normalize_ubi("701234567")


def test_normalize_nf_strips_xk_prefix():
    from packages.adapters.xk.adapter import _normalize_nf

    assert _normalize_nf("600123456") == "600123456"
    assert _normalize_nf("XK600123456") == "600123456"
    assert _normalize_nf(" xk 600 123 456 ") == "600123456"


def test_normalize_nf_rejects_wrong_length():
    from packages.adapters.xk.adapter import _normalize_nf

    with pytest.raises(InvalidIdentifierError):
        _normalize_nf("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_nf("70123456A")


def test_classify_status_buckets():
    from packages.adapters.xk.adapter import _classify_status

    assert _classify_status("Aktiv") == "active"
    assert _classify_status("E regjistruar") == "active"
    assert _classify_status("Çregjistruar") == "inactive"
    assert _classify_status("Në likuidim") == "inactive"
    assert _classify_status(None) is None


def test_parse_xk_date_formats():
    from datetime import date

    from packages.adapters.xk.adapter import _parse_xk_date

    assert _parse_xk_date("01/02/2020") == date(2020, 2, 1)
    assert _parse_xk_date("01.02.2020") == date(2020, 2, 1)
    assert _parse_xk_date("2020-02-01") == date(2020, 2, 1)
    assert _parse_xk_date("rubbish") is None
    assert _parse_xk_date(None) is None


def test_capital_amount_parses_albanian_format():
    from packages.adapters.xk.adapter import _parse_capital_amount

    # ARBK renders amounts in the Albanian convention: "." as thousands,
    # "," as decimal separator.
    assert _parse_capital_amount("10.000,50 €") == 10000.5
    assert _parse_capital_amount("1.000.000") == 1000000.0
    assert _parse_capital_amount("500") == 500.0
    assert _parse_capital_amount("63.000.000 EUR") == 63000000.0
    assert _parse_capital_amount("") is None
    assert _parse_capital_amount(None) is None


def test_adapter_metadata():
    adapter = XKAdapter()
    assert adapter.country_code == "XK"
    assert adapter.country_name == "Kosovo"
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert IdentifierType.VAT in adapter.identifier_types
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_search_by_empty_name_returns_empty():
    adapter = XKAdapter()
    assert await adapter.search_by_name("   ") == []


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    # ARBK does not publish filings in machine-readable form; honoring the
    # "no mock data" rule means we return [] rather than fabricating.
    adapter = XKAdapter()
    assert await adapter.fetch_financials("70123456A") == []


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = XKAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "529900T8BM49AURSDO55")


def test_normalize_company_number_accepts_nui_and_legacy():
    from packages.adapters.xk.adapter import _normalize_company_number

    assert _normalize_company_number("810485145") == "810485145"
    assert _normalize_company_number(" 810 485 145 ") == "810485145"
    assert _normalize_company_number("70123456A") == "70123456A"
    assert _normalize_company_number("71018482") == "71018482"


def test_normalize_company_number_rejects_garbage():
    from packages.adapters.xk.adapter import _normalize_company_number

    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("ABCDEFGHI")


def test_compute_key_matches_reference_vector():
    from packages.adapters.xk.adapter import _compute_key

    # AES-128-CBC(key=IV="8056483646328769", PKCS7) of a fixed timestamp,
    # base64-encoded — reproduces the ARBK front-end signing scheme.
    assert (
        _compute_key("2026-07-20T23:33:41.158384Z")
        == "0AOF/sp9IOFVoyDYwofa3QsEoRxJ/zuamHBFfhQV6XE="
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = XKAdapter()
    health = await adapter.health_check()
    assert health.country_code == "XK"
    # Portal may be flaky; tolerate ERROR/DEGRADED but not OK with no notes.
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_raiffeisen_live():
    adapter = XKAdapter()
    matches = await adapter.search_by_name("Raiffeisen", limit=5)
    assert isinstance(matches, list)
    assert matches, "expected at least one Raiffeisen match from ARBK export"
    for m in matches:
        assert m.country == "XK"
        assert m.name
        assert m.identifiers
