from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.py import PYAdapter
from packages.adapters.py.adapter import _clean_slug, _deslugify, _slugify
from packages.shared.models import FilingType, IdentifierType


def test_slugify_strips_accents_and_punctuation():
    assert _slugify("Codipsa S.A.") == "codipsa-s-a"
    assert _slugify("Almidón & Mandioca") == "almidon-mandioca"


def test_deslugify_drops_numeric_disambiguator():
    assert _deslugify("codipsa-2") == "CODIPSA"


def test_clean_slug_accepts_slug_and_url():
    assert _clean_slug("codipsa-2") == "codipsa-2"
    assert (
        _clean_slug("https://www.bolsadevalores.com.py/emisores/codipsa-2/")
        == "codipsa-2"
    )


def test_clean_slug_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _clean_slug("!!!")


def test_adapter_metadata():
    adapter = PYAdapter()
    assert adapter.country_code == "PY"
    assert adapter.country_name == "Paraguay"
    assert adapter.primary_identifier == IdentifierType.COMPANY_NUMBER
    assert IdentifierType.COMPANY_NUMBER in adapter.identifier_types
    assert adapter.requires_api_key is False
    assert adapter.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_id_type():
    adapter = PYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "codipsa-2")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_codipsa():
    adapter = PYAdapter()
    matches = await adapter.search_by_name("codipsa")
    assert any(m.id == "codipsa-2" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_returns_codipsa_details():
    adapter = PYAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "codipsa-2"
    )
    assert details is not None
    assert "CODIPSA" in details.name.upper()
    assert details.country == "PY"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_filings():
    adapter = PYAdapter()
    filings = await adapter.fetch_financials("codipsa-2", years=3)
    assert len(filings) >= 1
    latest = filings[0]
    assert latest.currency == "PYG"
    assert latest.type == FilingType.BALANCE_SHEET
    assert latest.document_url and latest.document_url.endswith(".zip")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = PYAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PY"
    assert health.capabilities == {
        "search": True,
        "lookup": True,
        "financials": True,
    }
