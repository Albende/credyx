"""Tests for the Colombia adapter (RUES).

Integration tests hit the live www.rues.org.co Consultas endpoint and are
marked `integration` so CI can skip them with `-m "not integration"`.
Per the project's no-mock-data rule the integration tests never use
canned fixtures.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.co import COAdapter
from packages.adapters.co.adapter import _nit_check_digit, _normalize_nit
from packages.shared.models import IdentifierType


def test_check_digit_ecopetrol() -> None:
    assert _nit_check_digit("899999068") == "1"


def test_check_digit_bancolombia() -> None:
    assert _nit_check_digit("890903938") == "8"


def test_check_digit_grupo_argos() -> None:
    assert _nit_check_digit("890900266") == "3"


def test_check_digit_avianca() -> None:
    assert _nit_check_digit("890100577") == "6"


def test_normalize_strips_dots_and_dash() -> None:
    body, check = _normalize_nit("899.999.068-1")
    assert body == "899999068"
    assert check == "1"


def test_normalize_strips_co_prefix() -> None:
    body, check = _normalize_nit("CO 899999068-1")
    assert body == "899999068"
    assert check == "1"


def test_normalize_accepts_body_only() -> None:
    body, check = _normalize_nit("899999068")
    assert body == "899999068"
    assert check is None


def test_normalize_eleven_digit_form_splits_check() -> None:
    # Without a dash, a 10-digit input is treated as a body-only NIT
    # (DIAN allows 10-digit bodies); 11 digits splits the trailing
    # check digit. The dashed form (e.g. "899999068-1") is the
    # canonical way to disambiguate when the body is 9 digits.
    body, check = _normalize_nit("8999990681")
    assert body == "8999990681"
    assert check is None
    body2, check2 = _normalize_nit("89099039388")
    assert body2 == "8909903938"
    assert check2 == "8"


def test_normalize_rejects_too_short() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_nit("12345")


def test_normalize_rejects_letters_in_body() -> None:
    with pytest.raises(InvalidIdentifierError):
        _normalize_nit("ABC999068-1")


@pytest.mark.asyncio
async def test_invalid_check_digit_rejected() -> None:
    adapter = COAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "899999068-9")


@pytest.mark.asyncio
async def test_wrong_identifier_type_rejected() -> None:
    adapter = COAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "899999068-1")


@pytest.mark.asyncio
async def test_empty_search_returns_empty_list() -> None:
    adapter = COAdapter()
    assert await adapter.search_by_name("   ") == []


@pytest.mark.asyncio
async def test_fetch_financials_unsupervised_returns_empty() -> None:
    # A non-SFC-supervised NIT must return [] not raise (per no-mock rule
    # we never fabricate filings).
    adapter = COAdapter()
    assert await adapter.fetch_financials("900123456") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live() -> None:
    adapter = COAdapter()
    health = await adapter.health_check()
    # Either OK (RUES reachable) or ERROR — both reflect reality, neither
    # is fabricated. We assert structure, not exact status, so transient
    # outages don't break CI.
    assert health.country_code == "CO"
    assert health.name == "Colombia"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_ecopetrol_nit() -> None:
    adapter = COAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "899.999.068-1"
    )
    # Skip rather than fail if RUES blocks the request from CI region;
    # this preserves the no-mock-data contract.
    if details is None:
        pytest.skip("RUES returned no record for Ecopetrol — region-blocked or offline")
    assert details.country == "CO"
    assert "ecopetrol" in details.name.lower()
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_bancolombia_nit_alias() -> None:
    adapter = COAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "890903938-8"
    )
    if details is None:
        pytest.skip("RUES returned no record for Bancolombia")
    assert "bancolombia" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_ecopetrol() -> None:
    adapter = COAdapter()
    try:
        matches = await adapter.search_by_name("ECOPETROL", limit=5)
    except AdapterNotImplementedError:
        pytest.skip("RUES response shape changed; see docs/countries/co.md")
    if not matches:
        pytest.skip("RUES returned no matches — region-blocked or offline")
    assert any("ecopetrol" in m.name.lower() for m in matches)
    assert all(m.country == "CO" for m in matches)
