from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.ru import RUAdapter
from packages.adapters.ru.adapter import (
    _classify_status,
    _extract_address,
    _extract_legal_form,
    _extract_name,
    _extract_okved,
    _normalize_inn,
    _normalize_ogrn,
    _parse_ru_date,
    _valid_inn,
)
from packages.shared.models import IdentifierType


def test_normalize_inn_accepts_10_and_12_digits():
    assert _normalize_inn("7707083893") == "7707083893"
    assert _normalize_inn(" 7707083893 ") == "7707083893"
    assert _normalize_inn("RU7707083893") == "7707083893"
    assert _normalize_inn("ru 7707083893") == "7707083893"
    assert _normalize_inn("7707-083-893") == "7707083893"


def test_normalize_inn_rejects_bad_shapes_and_checksums():
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("770708389A")
    with pytest.raises(InvalidIdentifierError):
        # 10 digits but wrong Mod-11 check digit.
        _normalize_inn("7707083890")
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("")


def test_inn_checksum_truth_table():
    # Real Russian taxpayer INNs — must validate.
    assert _valid_inn("7707083893")  # Sberbank
    assert _valid_inn("7736050003")  # Gazprom
    assert _valid_inn("7706107510")  # Rosneft
    assert _valid_inn("7736207543")  # Yandex LLC
    # Same digits with one swap — must fail.
    assert not _valid_inn("7707083894")
    # Wrong length — checksum should never accept these.
    assert not _valid_inn("770708389")     # 9 digits
    assert not _valid_inn("77070838933")   # 11 digits


def test_normalize_ogrn_accepts_13_and_15_digits():
    assert _normalize_ogrn("1027700132195") == "1027700132195"
    assert _normalize_ogrn("RU1027700132195") == "1027700132195"
    with pytest.raises(InvalidIdentifierError):
        _normalize_ogrn("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_ogrn("102770013219A")


def test_parse_ru_date_handles_common_formats():
    assert _parse_ru_date("1991-03-22").isoformat() == "1991-03-22"
    assert _parse_ru_date("22.03.1991").isoformat() == "1991-03-22"
    assert _parse_ru_date("22/03/1991").isoformat() == "1991-03-22"
    assert _parse_ru_date("") is None
    assert _parse_ru_date(None) is None
    assert _parse_ru_date("not a date") is None


def test_classify_status_maps_cyrillic_values():
    assert _classify_status("Действующее") == "active"
    assert _classify_status("Зарегистрировано") == "active"
    assert _classify_status("Ликвидировано") == "inactive"
    assert _classify_status("Прекращено") == "inactive"
    assert _classify_status("Недействующее") == "inactive"
    assert _classify_status(None) is None


def test_extract_helpers_read_egrul_rowshape():
    row = {
        "n": "ПАО Сбербанк",
        "i": "7707083893",
        "o": "1027700132195",
        "p": "773601001",
        "a": "г. Москва, ул. Вавилова, 19",
        "opf": "Публичное акционерное общество",
        "g": "Греф Герман Оскарович",
        "ok": "64.19",
        "st": "Действующее",
    }
    assert _extract_name(row) == "ПАО Сбербанк"
    assert _extract_address(row).startswith("г. Москва")
    assert _extract_legal_form(row).startswith("Публичное")
    assert _extract_okved(row) == ["64.19"]


def test_extract_okved_handles_list_of_dicts():
    row = {"okveds": [{"code": "64.19"}, {"code": "66.19"}]}
    assert _extract_okved(row) == ["64.19", "66.19"]


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = RUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "anything")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_inn():
    adapter = RUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "not-an-inn"
        )


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_ogrn():
    adapter = RUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "abc"
        )


@pytest.mark.asyncio
async def test_fetch_financials_rejects_garbage_identifier():
    adapter = RUAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-number")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = RUAdapter()
    health = await adapter.health_check()
    assert health.country_code == "RU"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_sberbank_by_inn():
    adapter = RUAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "7707083893"
    )
    assert details is not None
    assert details.country == "RU"
    assert details.name
    assert any(
        token in details.name.upper()
        for token in ("СБЕРБАНК", "SBERBANK", "СБЕР")
    )
    inns = [i.value for i in details.identifiers if i.type == IdentifierType.VAT]
    assert "7707083893" in inns


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_gazprom_by_ogrn():
    adapter = RUAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "1027700070518"
    )
    assert details is not None
    assert details.name
    assert any(
        token in details.name.upper() for token in ("ГАЗПРОМ", "GAZPROM")
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_rosneft():
    adapter = RUAdapter()
    matches = await adapter.search_by_name("Роснефть", limit=5)
    assert any(
        "РОСНЕФТЬ" in m.name.upper() or "ROSNEFT" in m.name.upper()
        for m in matches
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_returns_filings_for_sberbank():
    adapter = RUAdapter()
    filings = await adapter.fetch_financials("7707083893", years=5)
    # bo.nalog.ru indexes annual filings since 2019; Sberbank files every
    # year. We tolerate empty (geo-block / outage) but require well-typed
    # results when present.
    for f in filings:
        assert f.currency == "RUB"
        assert f.company_id == "7707083893"
        assert f.year >= 2019
