from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.mx import MXAdapter
from packages.adapters.mx.adapter import (
    _clean_name_for_edgar,
    _incorporation_from_rfc,
    _normalize_rfc,
)
from packages.shared.models import AdapterStatus, IdentifierType


def test_rfc_normalizer_accepts_known_companies():
    assert _normalize_rfc("PME380607P35") == "PME380607P35"
    assert _normalize_rfc("amo000925q31") == "AMO000925Q31"
    assert _normalize_rfc(" BIM660325IT8 ") == "BIM660325IT8"
    assert _normalize_rfc("WME-970924-4W4") == "WME9709244W4"


def test_rfc_normalizer_rejects_persona_fisica():
    with pytest.raises(InvalidIdentifierError, match="persona física"):
        _normalize_rfc("VECJ880326XXX")


def test_rfc_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_rfc("NOT-A-RFC")
    with pytest.raises(InvalidIdentifierError):
        _normalize_rfc("PEP97AB14I20")


def test_incorporation_date_decoded_from_rfc():
    assert _incorporation_from_rfc("PME380607P35").isoformat() == "1938-06-07"
    assert _incorporation_from_rfc("AMO000925Q31").isoformat() == "2000-09-25"


def test_clean_name_for_edgar_strips_legal_form():
    assert _clean_name_for_edgar("AMERICA MOVIL S A B DE C V") == "AMERICA MOVIL"
    assert _clean_name_for_edgar("PETROLEOS MEXICANOS EPE") == "PETROLEOS MEXICANOS"


@pytest.mark.asyncio
async def test_lookup_invalid_identifier_type():
    adapter = MXAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.KRS, "PME380607P35")


@pytest.mark.asyncio
async def test_fetch_financials_validates_rfc():
    adapter = MXAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("garbage")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_gleif():
    adapter = MXAdapter()
    health = await adapter.health_check()
    assert health.country_code == "MX"
    assert health.status in (AdapterStatus.OK, AdapterStatus.ERROR)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_real_matches():
    adapter = MXAdapter()
    matches = await adapter.search_by_name("America Movil", limit=5)
    assert matches
    assert any("MOVIL" in m.name.upper() for m in matches)
    assert all(m.country == "MX" for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_rfc_returns_details():
    adapter = MXAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "AMO000925Q31")
    assert details is not None
    assert "MOVIL" in details.name.upper()
    assert details.country == "MX"
    assert any(i.type == IdentifierType.LEI for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_annual_reports():
    adapter = MXAdapter()
    filings = await adapter.fetch_financials("PME380607P35", years=3)
    assert filings
    assert filings[0].document_url and filings[0].document_url.startswith("https://")
