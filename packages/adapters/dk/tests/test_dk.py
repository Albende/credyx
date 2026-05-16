"""Integration tests for the Denmark (CVR / virk.dk) adapter.

These tests hit the real distribution.virk.dk ElasticSearch endpoint and
therefore require valid Basic-auth credentials in the environment. They
are skipped automatically when credentials are missing.
"""
from __future__ import annotations

import os

import pytest

from packages.adapters.dk import DKAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.shared.models import IdentifierType


def _skip_if_no_creds() -> None:
    if not (os.getenv("DK_VIRK_USERNAME") and os.getenv("DK_VIRK_PASSWORD")):
        pytest.skip("missing DK_VIRK_USERNAME/PASSWORD")


def test_cvr_normalization_strips_vat_prefix():
    from packages.adapters.dk.adapter import _normalize_cvr

    assert _normalize_cvr("DK22756214") == "22756214"
    assert _normalize_cvr("22 756 214") == "22756214"
    assert _normalize_cvr("22.756.214") == "22756214"


def test_cvr_normalization_rejects_garbage():
    from packages.adapters.dk.adapter import _normalize_cvr

    with pytest.raises(InvalidIdentifierError):
        _normalize_cvr("1234")
    with pytest.raises(InvalidIdentifierError):
        _normalize_cvr("ABCDEFGH")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_maersk():
    _skip_if_no_creds()
    adapter = DKAdapter()
    matches = await adapter.search_by_name("A.P. Møller - Mærsk", limit=10)
    assert matches, "expected at least one Maersk hit"
    assert any("mærsk" in m.name.lower() or "maersk" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_maersk_cvr():
    _skip_if_no_creds()
    adapter = DKAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "22756214"
    )
    assert details is not None
    assert details.country == "DK"
    assert details.id == "22756214"
    assert any(i.type == IdentifierType.COMPANY_NUMBER for i in details.identifiers)
    assert any(
        i.type == IdentifierType.VAT and i.value == "DK22756214"
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_accepts_vat_prefix():
    _skip_if_no_creds()
    adapter = DKAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "DK24256790")
    assert details is not None
    assert details.id == "24256790"
    assert "novo" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_financials_maersk_non_empty():
    _skip_if_no_creds()
    adapter = DKAdapter()
    filings = await adapter.fetch_financials("22756214", years=5)
    assert filings, "expected at least one Maersk annual report"
    f = filings[0]
    assert f.company_id == "22756214"
    assert f.currency == "DKK"
    assert f.document_url, "annual report should have a document URL"
