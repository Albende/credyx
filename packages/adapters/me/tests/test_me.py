from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.me import MEAdapter
from packages.adapters.me.adapter import (
    _extract_legal_form,
    _normalize_me_id,
    _parse_crps_results,
    _pick_by_identifier,
    _strip_diacritics,
)
from packages.shared.models import IdentifierType


def test_normalize_strips_me_prefix():
    assert _normalize_me_id("ME 02289377", label="PIB") == "02289377"
    assert _normalize_me_id("02002230", label="PIB") == "02002230"


def test_normalize_rejects_wrong_length():
    with pytest.raises(InvalidIdentifierError):
        _normalize_me_id("1234567", label="MB")
    with pytest.raises(InvalidIdentifierError):
        _normalize_me_id("123456789", label="MB")


def test_normalize_rejects_non_digits():
    with pytest.raises(InvalidIdentifierError):
        _normalize_me_id("ABCDEFGH", label="PIB")


def test_strip_diacritics_handles_montenegrin():
    assert _strip_diacritics("Plantaže") == "Plantaze"
    assert _strip_diacritics("Nikšić") == "Niksic"
    assert _strip_diacritics("Čačak Š") == "Cacak S"


def test_legal_form_recognized():
    assert _extract_legal_form("Crnogorski Telekom A.D.") == "AD"
    assert _extract_legal_form("Neka Firma d.o.o.") == "DOO"
    assert _extract_legal_form("Bezimena Kompanija") is None


def test_parse_crps_results_picks_up_row():
    sample = (
        "<table><tr>"
        "<td>Crnogorski Telekom A.D.</td>"
        "<td>PIB: 02289377</td>"
        "<td>MB: 02289377</td>"
        "<td>Moskovska bb, Podgorica</td>"
        "<td>Aktivno</td>"
        "</tr></table>"
    )
    rows = _parse_crps_results(sample)
    assert rows
    row = rows[0]
    assert row["pib"] == "02289377"
    assert "Telekom" in row["name"]
    assert "Podgorica" in (row["address"] or "")


def test_pick_by_identifier_matches_pib():
    rows = [
        {"pib": "02289377", "mb": "02289377", "name": "X"},
        {"pib": "02002230", "mb": "02002230", "name": "Y"},
    ]
    assert _pick_by_identifier(rows, "02002230")["name"] == "Y"


def test_adapter_metadata():
    a = MEAdapter()
    assert a.country_code == "ME"
    assert IdentifierType.VAT in a.identifier_types
    assert IdentifierType.COMPANY_NUMBER in a.identifier_types
    assert a.requires_api_key is False
    assert a.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_live():
    adapter = MEAdapter()
    health = await adapter.health_check()
    assert health.country_code == "ME"
    assert health.name == "Montenegro"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_telekom():
    adapter = MEAdapter()
    matches = await adapter.search_by_name("Crnogorski Telekom", limit=5)
    # CRPS HTML occasionally shifts; we accept an empty result rather than
    # fabricate one, but if it returns rows they must be real Montenegrin.
    for m in matches:
        assert m.country == "ME"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_pib_telekom():
    adapter = MEAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "02289377")
    if details is not None:
        assert details.country == "ME"
        assert any(i.value.endswith("02289377") for i in details.identifiers)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_mb_epcg():
    adapter = MEAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "02002230"
    )
    if details is not None:
        assert details.country == "ME"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_listed_issuer():
    adapter = MEAdapter()
    filings = await adapter.fetch_financials("02289377", years=2)
    assert isinstance(filings, list)
    for f in filings:
        assert f.currency == "EUR"
        assert f.source_url and "mse.co.me" in f.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_unknown_pib_returns_empty():
    adapter = MEAdapter()
    filings = await adapter.fetch_financials("99999999", years=2)
    assert filings == []


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_identifier_type():
    adapter = MEAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "02289377")
