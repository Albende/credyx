from __future__ import annotations

import pytest

from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
from packages.adapters.de import DEAdapter
from packages.shared.models import (
    AdapterStatus,
    IdentifierType,
)


def _skip_if_upstream_offline(exc: BaseException) -> None:
    msg = str(exc).lower()
    if "offline" in msg or "unreachable" in msg or "non-json" in msg:
        pytest.skip(f"OffeneRegister upstream offline: {exc}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = DEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "DE"
    assert health.status in (AdapterStatus.OK, AdapterStatus.ERROR)
    if health.status == AdapterStatus.OK:
        assert health.capabilities["search"] is True
        assert health.capabilities["lookup"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_siemens():
    adapter = DEAdapter()
    try:
        matches = await adapter.search_by_name("Siemens", limit=10)
    except AdapterError as exc:
        _skip_if_upstream_offline(exc)
        raise
    assert isinstance(matches, list)
    assert len(matches) >= 1
    assert any("siemens" in m.name.lower() for m in matches)
    assert all(m.country == "DE" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_bmw():
    adapter = DEAdapter()
    try:
        matches = await adapter.search_by_name("Bayerische Motoren Werke", limit=10)
    except AdapterError as exc:
        _skip_if_upstream_offline(exc)
        raise
    assert any(
        "bmw" in m.name.lower() or "bayerische motoren" in m.name.lower()
        for m in matches
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_sap():
    adapter = DEAdapter()
    try:
        matches = await adapter.search_by_name("SAP SE", limit=10)
    except AdapterError as exc:
        _skip_if_upstream_offline(exc)
        raise
    assert any("sap" in m.name.lower() for m in matches)
    assert any(
        any(i.type == IdentifierType.COMPANY_NUMBER for i in m.identifiers)
        for m in matches
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_hrb_bmw():
    adapter = DEAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.HRB, "HRB 42243 München"
        )
    except AdapterError as exc:
        _skip_if_upstream_offline(exc)
        raise
    if details is None:
        pytest.skip("OffeneRegister did not return a BMW match for HRB 42243 München")
    assert details.country == "DE"
    assert "bmw" in details.name.lower() or "bayerische motoren" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_company_number_slug():
    adapter = DEAdapter()
    try:
        matches = await adapter.search_by_name("Volkswagen AG", limit=5)
    except AdapterError as exc:
        _skip_if_upstream_offline(exc)
        raise
    slug_match = next(
        (
            m
            for m in matches
            if any(i.type == IdentifierType.COMPANY_NUMBER for i in m.identifiers)
            and "volkswagen" in m.name.lower()
        ),
        None,
    )
    if slug_match is None:
        pytest.skip("OffeneRegister did not return a Volkswagen slug")
    slug = next(
        i.value for i in slug_match.identifiers if i.type == IdentifierType.COMPANY_NUMBER
    )
    try:
        details = await adapter.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, slug)
    except AdapterError as exc:
        _skip_if_upstream_offline(exc)
        raise
    assert details is not None
    assert details.id == slug
    assert "volkswagen" in details.name.lower()


def test_invalid_vat_format_rejected():
    adapter = DEAdapter()
    import asyncio

    with pytest.raises(InvalidIdentifierError):
        asyncio.run(
            adapter.lookup_by_identifier(IdentifierType.VAT, "FR12345678901")
        )


def test_invalid_hrb_format_rejected():
    adapter = DEAdapter()
    import asyncio

    with pytest.raises(InvalidIdentifierError):
        asyncio.run(adapter.lookup_by_identifier(IdentifierType.HRB, "garbage 999"))


def test_unsupported_identifier_rejected():
    adapter = DEAdapter()
    import asyncio

    with pytest.raises(InvalidIdentifierError):
        asyncio.run(
            adapter.lookup_by_identifier(IdentifierType.SIREN, "123456789")
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_does_not_crash():
    adapter = DEAdapter()
    try:
        matches = await adapter.search_by_name("Siemens AG", limit=5)
    except AdapterError as exc:
        _skip_if_upstream_offline(exc)
        raise
    if not matches:
        pytest.skip("no Siemens match from OffeneRegister")
    slug = matches[0].id
    filings = await adapter.fetch_financials(slug, years=3)
    # Best-effort scrape — empty list is acceptable per spec.
    assert isinstance(filings, list)
    for f in filings:
        assert f.year >= 2000
        assert f.currency == "EUR"
        assert f.company_id == slug
