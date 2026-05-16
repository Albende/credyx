"""Tests for the ZA (BizPortal + JSE) adapter.

Integration tests hit BizPortal directly and are marked `integration` so CI
can skip them with `-m "not integration"`. Unit tests cover the registration
number parser, VAT validator, HTML helpers, and the fact that financials
return [] rather than fabricated rows.
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
    _looks_blocked,
    _normalize_company_number,
    _normalize_vat,
    _parse_search_results,
    _strip_html,
)
from packages.shared.models import IdentifierType


def test_normalize_canonical_form():
    assert _normalize_company_number("1925/001431/06") == "1925/0001431/06"


def test_normalize_pads_seven_digit_sequence():
    # CIPC pads sequence to 7 digits; canonical Naspers value already is.
    assert _normalize_company_number("1925/0001431/06") == "1925/0001431/06"


def test_normalize_accepts_dashes_and_spaces():
    assert _normalize_company_number("1969-017128-06") == "1969/0017128/06"
    assert _normalize_company_number(" 1994 009584 06 ") == "1994/0009584/06"


def test_normalize_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("ZA-BOGUS")
    with pytest.raises(InvalidIdentifierError):
        _normalize_company_number("19/001431/06")


def test_normalize_vat_accepts_canonical():
    assert _normalize_vat("4012345678") == "4012345678"
    assert _normalize_vat(" 4012345678 ") == "4012345678"


def test_normalize_vat_rejects_bad_prefix_or_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("5012345678")
    with pytest.raises(InvalidIdentifierError):
        _normalize_vat("40123456")


def test_strip_html_collapses_tags_and_whitespace():
    raw = "<div>Hello\n  <b>world</b></div>"
    assert _strip_html(raw) == "Hello world"


def test_looks_blocked_detects_captcha_markers():
    assert _looks_blocked("Please complete the CAPTCHA challenge")
    assert _looks_blocked("Access Denied by Cloudflare")
    assert not _looks_blocked("<html><body>BizPortal search</body></html>")


def test_parse_search_results_picks_up_registration_pairs():
    html = """
    <table>
      <tr><td>Naspers Limited</td><td>1925/001431/06</td></tr>
      <tr><td>Standard Bank Group Limited</td><td>1969/017128/06</td></tr>
    </table>
    """
    matches = _parse_search_results(html, limit=10)
    names = {m.name for m in matches}
    regs = {m.id for m in matches}
    assert "Naspers Limited" in names
    assert "1925/0001431/06" in regs
    assert "1969/0017128/06" in regs


def test_parse_search_results_dedupes_repeats():
    html = """
    <tr><td>Acme</td><td>2010/000001/07</td></tr>
    <tr><td>Acme</td><td>2010/000001/07</td></tr>
    """
    matches = _parse_search_results(html, limit=10)
    assert len(matches) == 1


def test_fetch_financials_returns_empty_for_listed_or_unlisted():
    adapter = ZAAdapter()
    # Naspers — listed on JSE — but free financials aren't wired.
    result = asyncio.run(adapter.fetch_financials("1925/001431/06"))
    assert result == []


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
async def test_health_check_against_bizportal():
    adapter = ZAAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ZA"
    # OK, DEGRADED, BLOCKED, or ERROR are all acceptable — we only require a
    # real response shape and no exception.
    assert health.status.value in {"ok", "degraded", "blocked", "error"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_naspers_returns_something_or_clean_501():
    adapter = ZAAdapter()
    try:
        matches = await adapter.search_by_name("Naspers", limit=5)
    except AdapterNotImplementedError:
        # Acceptable: BizPortal markup may have changed; we never fabricate.
        return
    # If we did parse, at least one row should reference a CIPC-format reg #.
    assert all(m.country == "ZA" for m in matches)
    for m in matches:
        assert any(
            i.type == IdentifierType.COMPANY_NUMBER for i in m.identifiers
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_naspers_by_registration_number():
    adapter = ZAAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "1925/001431/06"
        )
    except AdapterNotImplementedError:
        return
    if details is None:
        return
    assert details.country == "ZA"
    assert any(
        i.value == "1925/0001431/06" and i.type == IdentifierType.COMPANY_NUMBER
        for i in details.identifiers
    )
