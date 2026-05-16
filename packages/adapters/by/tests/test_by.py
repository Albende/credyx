from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.by import BYAdapter
from packages.adapters.by.adapter import (
    _classify_status,
    _extract_address,
    _extract_legal_form,
    _extract_name,
    _extract_reg_date,
    _extract_status,
    _normalize_unp,
    _parse_by_date,
    _records_from_payload,
)
from packages.shared.models import IdentifierType


def test_normalize_unp_strips_prefix_and_whitespace():
    assert _normalize_unp("600122610") == "600122610"
    assert _normalize_unp(" 600122610 ") == "600122610"
    assert _normalize_unp("BY600122610") == "600122610"
    assert _normalize_unp("by 600122610") == "600122610"
    assert _normalize_unp("600-122-610") == "600122610"


def test_normalize_unp_rejects_invalid_lengths():
    with pytest.raises(InvalidIdentifierError):
        _normalize_unp("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_unp("6001226100")  # 10 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_unp("60012ABCD")
    with pytest.raises(InvalidIdentifierError):
        _normalize_unp("")


def test_parse_by_date_handles_common_formats():
    assert _parse_by_date("1992-04-15").isoformat() == "1992-04-15"
    assert _parse_by_date("15.04.1992").isoformat() == "1992-04-15"
    assert _parse_by_date("15/04/1992").isoformat() == "1992-04-15"
    assert _parse_by_date("") is None
    assert _parse_by_date(None) is None
    assert _parse_by_date("not a date") is None


def test_classify_status_maps_cyrillic_values():
    assert _classify_status("Действующее") == "active"
    assert _classify_status("зарегистрировано") == "active"
    assert _classify_status("Ликвидировано") == "inactive"
    assert _classify_status("Прекращено") == "inactive"
    assert _classify_status(None) is None


def test_records_from_payload_handles_list_and_dict():
    assert _records_from_payload(None) == []
    assert _records_from_payload([{"a": 1}, "skip", {"b": 2}]) == [
        {"a": 1},
        {"b": 2},
    ]
    assert _records_from_payload({"data": [{"x": 1}]}) == [{"x": 1}]
    assert _records_from_payload({"vnaim": "ОАО Беларуськалий"}) == [
        {"vnaim": "ОАО Беларуськалий"}
    ]


def test_extract_helpers_read_egr_fields():
    record = {
        "ngrn": "600122610",
        "vnaim": "ОАО Беларуськалий",
        "vnaimsostgo": "Действующее",
        "vnaimop": "Открытое акционерное общество",
        "dregdate": "1990-03-27",
    }
    assert _extract_name(record) == "ОАО Беларуськалий"
    assert _extract_status(record) == "Действующее"
    assert _extract_legal_form(record) == "Открытое акционерное общество"
    assert _extract_reg_date(record) == "1990-03-27"


def test_extract_address_concatenates_parts():
    record = {
        "vpadres": "г. Солигорск, ул. Коржа, 5",
    }
    assert "Солигорск" in (_extract_address(record) or "")

    parts_record = {
        "vnp": "Минск",
        "vstreet": "пр. Независимости",
        "vhouse": "11",
    }
    out = _extract_address(parts_record) or ""
    assert "Минск" in out
    assert "Независимости" in out


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = BYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "any")


@pytest.mark.asyncio
async def test_lookup_rejects_malformed_unp():
    adapter = BYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "not-a-number"
        )


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_valid_unp():
    adapter = BYAdapter()
    filings = await adapter.fetch_financials("600122610")
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_malformed_unp():
    adapter = BYAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("12")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = BYAdapter()
    health = await adapter.health_check()
    assert health.country_code == "BY"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_belaruskali_by_unp():
    adapter = BYAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "600122610"
    )
    assert details is not None
    assert details.country == "BY"
    assert details.id == "600122610"
    assert details.name
    # Match Russian or transliterated Latin name.
    assert any(
        token in details.name.upper()
        for token in ("БЕЛАРУСЬКАЛИЙ", "BELARUSKALI", "КАЛИЙ")
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_belaz_via_vat_identifier():
    adapter = BYAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "BY600354898"
    )
    assert details is not None
    assert details.id == "600354898"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_finds_belaz():
    adapter = BYAdapter()
    matches = await adapter.search_by_name("БЕЛАЗ", limit=5)
    assert any(
        "БЕЛАЗ" in m.name.upper() or "BELAZ" in m.name.upper() for m in matches
    )
