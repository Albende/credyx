from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.se import SEAdapter
from packages.adapters.se.adapter import (
    _luhn_ok,
    _normalize_orgnr,
    _normalize_se_vat,
)
from packages.shared.models import AdapterStatus, IdentifierType


def test_luhn_known_good():
    # Volvo, Ericsson, H&M — all real Swedish Organisationsnummer.
    for orgnr in (
        "5560125790",
        "5560160680",
        "5560427220",
    ):
        assert _luhn_ok(orgnr), orgnr


def test_luhn_rejects_tweaked_check_digit():
    assert not _luhn_ok("5560125791")


def test_luhn_rejects_wrong_length():
    assert not _luhn_ok("556012579")
    assert not _luhn_ok("55601257900")


def test_luhn_rejects_non_digits():
    assert not _luhn_ok("55601257ab")


def test_normalize_orgnr_accepts_dashed_form():
    assert _normalize_orgnr("556012-5790") == "5560125790"


def test_normalize_orgnr_strips_country_prefix_and_separators():
    assert _normalize_orgnr("SE556012-5790") == "5560125790"
    assert _normalize_orgnr(" 556 012 5790 ") == "5560125790"
    assert _normalize_orgnr("5560125790") == "5560125790"


def test_normalize_orgnr_accepts_vat_shaped_input():
    # If someone passes a 12-digit VAT under the COMPANY_NUMBER type, we
    # tolerate it by dropping the trailing "01".
    assert _normalize_orgnr("556012579001") == "5560125790"
    assert _normalize_orgnr("SE556012579001") == "5560125790"


def test_normalize_orgnr_rejects_bad_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_orgnr("12345")


def test_normalize_orgnr_rejects_bad_checksum():
    with pytest.raises(InvalidIdentifierError):
        _normalize_orgnr("5560125791")


def test_normalize_se_vat_canonical_form():
    assert _normalize_se_vat("SE556012579001") == "556012579001"
    assert _normalize_se_vat("556012579001") == "556012579001"


def test_normalize_se_vat_pads_org_nr_with_01_suffix():
    assert _normalize_se_vat("SE5560125790") == "556012579001"
    assert _normalize_se_vat("5560125790") == "556012579001"


def test_normalize_se_vat_rejects_wrong_suffix():
    # SE VAT must end in "01" — any other suffix indicates a malformed
    # input or a non-Swedish VAT.
    with pytest.raises(InvalidIdentifierError):
        _normalize_se_vat("556012579002")


def test_normalize_se_vat_rejects_bad_orgnr_checksum():
    with pytest.raises(InvalidIdentifierError):
        _normalize_se_vat("556012579101")


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = SEAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Volvo")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = SEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.SIREN, "5560125790")


@pytest.mark.asyncio
async def test_fetch_financials_unlisted_returns_empty():
    adapter = SEAdapter()
    # An org nr that Luhn-validates but is not in the listed-issuer map.
    # 0000000000 passes the Swedish Luhn check (all-zero check digit).
    assert _luhn_ok("0000000000")
    filings = await adapter.fetch_financials("0000000000", years=5)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = SEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "SE"
    assert health.status in (AdapterStatus.OK, AdapterStatus.DEGRADED)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_volvo_via_vies():
    adapter = SEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "SE556012579001"
    )
    assert details is not None
    assert details.country == "SE"
    assert details.id == "5560125790"
    assert "volvo" in details.name.lower()
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ericsson_via_vies_by_orgnr():
    adapter = SEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "556016-0680"
    )
    assert details is not None
    assert "ericsson" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_hm_via_vies():
    adapter = SEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "SE556042722001"
    )
    assert details is not None
    # H&M's registered name in VIES is "H & M HENNES & MAURITZ AB".
    assert "hennes" in details.name.lower() or "h & m" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_returns_nasdaq_links():
    adapter = SEAdapter()
    filings = await adapter.fetch_financials("5560125790", years=3)
    assert len(filings) == 3
    for f in filings:
        assert f.currency == "SEK"
        assert f.document_url is not None
        assert "nasdaq.com" in f.document_url
