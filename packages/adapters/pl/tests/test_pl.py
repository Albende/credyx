from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.pl import PLAdapter
from packages.adapters.pl.adapter import (
    _ceidg_firma_to_details,
    _ceidg_item_to_match,
    _format_ceidg_address,
    _format_pkd,
    _is_valid_nip,
    _normalize_krs,
    _normalize_nip,
    _normalize_regon,
    _sole_trader_details_from_biala,
)
from packages.shared.models import IdentifierType


def test_normalize_krs_pads_short_numbers():
    assert _normalize_krs("28860") == "0000028860"
    assert _normalize_krs(" 0000028860 ") == "0000028860"


def test_normalize_krs_rejects_non_digits():
    with pytest.raises(InvalidIdentifierError):
        _normalize_krs("ABCDEFGHIJ")


def test_normalize_nip_strips_prefix_and_validates_checksum():
    assert _normalize_nip("PL 774-000-14-54") == "7740001454"


def test_normalize_nip_rejects_bad_checksum():
    with pytest.raises(InvalidIdentifierError):
        _normalize_nip("7740001455")


def test_normalize_regon_accepts_9_and_14_digit():
    assert _normalize_regon("610188201") == "610188201"
    assert _normalize_regon("61018820100000") == "61018820100000"


def test_normalize_regon_pads_8_digit_leading_zero():
    # Aggregators drop the leading zero of 9-digit REGONs; we restore it.
    assert _normalize_regon("21405924") == "021405924"


def test_is_valid_nip():
    assert _is_valid_nip("6121719035")  # AKTIV JUSTYNA OSIP
    assert _is_valid_nip("PL 774-000-14-54")
    assert not _is_valid_nip("6121719036")
    assert not _is_valid_nip("0000028860")  # a KRS, not a NIP


def test_format_pkd_and_address():
    assert _format_pkd("4711Z") == "47.11.Z"
    assert _format_pkd("6201Z") == "62.01.Z"
    assert (
        _format_ceidg_address(
            {"ulica": "ul. Zabobrze", "budynek": "27H", "kod": "59-700",
             "miasto": "Bolesławiec", "kraj": "PL"}
        )
        == "ul. Zabobrze 27H, 59-700 Bolesławiec, PL"
    )


def test_sole_trader_details_from_biala():
    subject = {
        "name": "JUSTYNA OSIP",
        "nip": "6121719035",
        "regon": "021405924",
        "krs": None,
        "statusVat": "Czynny",
        "residenceAddress": "ZABOBRZE 27H, 59-700 BOLESŁAWIEC",
        "registrationLegalDate": "2010-12-01",
        "accountNumbers": ["12102021370000940201929215"],
    }
    details = _sole_trader_details_from_biala(subject)
    assert details.id == "6121719035"
    assert details.name == "JUSTYNA OSIP"
    assert details.country == "PL"
    assert details.status == "active"
    assert details.incorporation_date is not None
    nip = [i for i in details.identifiers if i.type == IdentifierType.NIP]
    regon = [i for i in details.identifiers if i.type == IdentifierType.REGON]
    assert nip and nip[0].value == "6121719035"
    assert regon and regon[0].value == "021405924"


def test_ceidg_item_to_match_and_details():
    item = {
        "id": "149AC884-8F57-4636-BA86-848AC6AA5146",
        "nazwa": "AKTIV JUSTYNA OSIP",
        "status": "AKTYWNY",
        "dataRozpoczecia": "2010-12-01",
        "adresDzialalnosci": {
            "ulica": "ul. Zabobrze", "budynek": "27H",
            "kod": "59-700", "miasto": "Bolesławiec", "kraj": "PL",
        },
        "wlasciciel": {
            "imie": "Justyna", "nazwisko": "Osip",
            "nip": "6121719035", "regon": "021405924",
        },
        "pkdGlowny": {"kod": "0111Z", "nazwa": "..."},
    }
    match = _ceidg_item_to_match(item)
    assert match.name == "AKTIV JUSTYNA OSIP"
    assert match.id == "6121719035"
    assert match.status == "active"
    assert any(i.value == "6121719035" for i in match.identifiers)

    details = _ceidg_firma_to_details(item)
    assert details.name == "AKTIV JUSTYNA OSIP"
    assert details.legal_form and "sole proprietorship" in details.legal_form.lower()
    assert details.nace_codes == ["01.11.Z"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_orlen_by_krs():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.KRS, "0000028860")
    assert details is not None
    assert "ORLEN" in details.name.upper()
    assert details.country == "PL"
    nip_ids = [i for i in details.identifiers if i.type == IdentifierType.NIP]
    assert nip_ids and nip_ids[0].value == "7740001454"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_cd_projekt_pulls_capital_and_nace():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.KRS, "0000006865")
    assert details is not None
    assert "CD PROJEKT" in details.name.upper()
    assert details.capital_currency == "PLN"
    assert details.capital_amount is not None and details.capital_amount > 0
    assert any(code.startswith("62") for code in details.nace_codes)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_nip_resolves_via_biala_lista():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.NIP, "7740001454")
    assert details is not None
    assert details.id == "0000028860"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_vat_with_pl_prefix():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.VAT, "PL6920000013")
    assert details is not None
    assert "KGHM" in details.name.upper()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_sole_trader_by_nip_via_biala_lista():
    # AKTIV JUSTYNA OSIP is a CEIDG-registered sole trader (JDG), NOT in KRS.
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.NIP, "6121719035")
    assert details is not None
    assert details.id == "6121719035"
    assert "OSIP" in details.name.upper()
    assert details.legal_form and "sole proprietorship" in details.legal_form.lower()
    regon = [i for i in details.identifiers if i.type == IdentifierType.REGON]
    assert regon and regon[0].value == "021405924"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_sole_trader_by_regon_via_biala_lista():
    adapter = PLAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.REGON, "021405924")
    assert details is not None
    assert "OSIP" in details.name.upper()
    nip = [i for i in details.identifiers if i.type == IdentifierType.NIP]
    assert nip and nip[0].value == "6121719035"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_empty_for_sole_trader():
    adapter = PLAdapter()
    filings = await adapter.fetch_financials("6121719035")
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_ok():
    adapter = PLAdapter()
    health = await adapter.health_check()
    assert health.country_code == "PL"
    assert health.status.value in {"ok", "degraded"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_empty_for_blocked_rdf():
    adapter = PLAdapter()
    filings = await adapter.fetch_financials("0000028860")
    assert filings == []
