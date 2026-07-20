"""Tests for the ZA (GLEIF + SEC EDGAR) adapter.

Integration tests hit GLEIF and SEC EDGAR directly and are marked
`integration` so CI can skip them with `-m "not integration"`. Unit tests
cover the registration-number parser, VAT validator, name normalization,
and document-format helper.
"""
from __future__ import annotations

import asyncio

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.za import ZAAdapter
from packages.adapters.za.adapter import (
    _core_name,
    _doc_format,
    _name_matches,
    _normalize_company_number,
    _normalize_vat,
    _reg_variants,
)
from packages.shared.models import IdentifierType


def test_normalize_preserves_sequence_digits():
    # CIPC stores the sequence without forced padding; preserve it as given.
    assert _normalize_company_number("1979/003231/06") == "1979/003231/06"
    assert _normalize_company_number("1925/001431/06") == "1925/001431/06"


def test_normalize_accepts_dashes_and_spaces():
    assert _normalize_company_number("1969-017128-06") == "1969/017128/06"
    assert _normalize_company_number(" 1994 009584 06 ") == "1994/009584/06"


def test_normalize_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("ZA-BOGUS")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("19/001431/06")


def test_reg_variants_covers_padding_widths():
    variants = _reg_variants("1979/003231/06")
    assert "1979/003231/06" in variants
    assert "1979/0003231/06" in variants
    assert "1979/003231/06" in variants


def test_normalize_vat_accepts_canonical():
    assert _normalize_vat("4012345678") == "4012345678"
    assert _normalize_vat(" 4012345678 ") == "4012345678"


def test_normalize_vat_rejects_bad_prefix_or_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("5012345678")
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("40123456")


def test_core_name_strips_corporate_suffixes():
    assert _core_name("Sasol Limited") == "SASOL"
    assert _core_name("Standard Bank Group Limited") == "STANDARD BANK"


def test_name_matches_across_suffix_variants():
    assert _name_matches(_core_name("Sasol Limited"), "SASOL LTD")
    assert not _name_matches(_core_name("Sasol Limited"), "MTN GROUP")


def test_doc_format_from_extension():
    assert _doc_format("ssl-20250630x20f.htm") == "html"
    assert _doc_format("report.pdf") == "pdf"
    assert _doc_format("facts.xml") == "xbrl"
    assert _doc_format(None) is None


def test_lookup_by_vat_raises_not_implemented():
    adapter = ZAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        asyncio.run(adapter.lookup_by_identifier(IdentifierType.VAT, "4012345678"))


def test_lookup_with_invalid_type_raises():
    adapter = ZAAdapter()
    with pytest.raises(InvalidIdentifierError):
        asyncio.run(
            adapter.lookup_by_identifier(IdentifierType.SIREN, "1925/001431/06")
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_against_gleif():
    adapter = ZAAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ZA"
    assert health.status.value in {"ok", "degraded", "error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_sasol_returns_cipc_numbers():
    adapter = ZAAdapter()
    matches = await adapter.search_by_name("Sasol", limit=5)
    assert matches
    assert all(m.country == "ZA" for m in matches)
    assert any(
        any(i.type == IdentifierType.COMPANY_NUMBER for i in m.identifiers)
        for m in matches
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_sasol_by_registration_number():
    adapter = ZAAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "1979/003231/06"
    )
    assert details is not None
    assert details.country == "ZA"
    assert "sasol" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_sasol_returns_20f():
    adapter = ZAAdapter()
    filings = await adapter.fetch_financials("1979/003231/06", years=3)
    assert filings
    for f in filings:
        assert f.document_url and "sec.gov" in f.document_url
        assert f.type.value == "annual_report"
