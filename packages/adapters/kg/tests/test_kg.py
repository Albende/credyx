from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.kg import KGAdapter
from packages.adapters.kg.adapter import (
    _classify_status,
    _extract_company_record,
    _extract_search_results,
    _normalize_inn,
    _parse_capital,
    _parse_kg_date,
)
from packages.shared.models import IdentifierType


def test_normalize_inn_accepts_clean_fourteen_digits():
    assert _normalize_inn("01410199810177") == "01410199810177"
    assert _normalize_inn(" 01410199810177 ") == "01410199810177"
    assert _normalize_inn("01410-19981-0177") == "01410199810177"
    assert _normalize_inn("KG01410199810177") == "01410199810177"
    assert _normalize_inn("kg 02401199810064") == "02401199810064"


def test_normalize_inn_rejects_wrong_length_or_chars():
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("1234")
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("014101998101771")  # 15 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("0141019981017A")
    with pytest.raises(InvalidIdentifierError):
        _normalize_inn("")


def test_parse_kg_date_handles_common_formats():
    assert _parse_kg_date("15.04.1995").isoformat() == "1995-04-15"
    assert _parse_kg_date("1995-04-15").isoformat() == "1995-04-15"
    assert _parse_kg_date("15/04/1995").isoformat() == "1995-04-15"
    assert _parse_kg_date("") is None
    assert _parse_kg_date(None) is None
    assert _parse_kg_date("not a date") is None


def test_classify_status_handles_russian_and_english():
    assert _classify_status("Действующее") == "active"
    assert _classify_status("действующий") == "active"
    assert _classify_status("Active") == "active"
    assert _classify_status("Ликвидировано") == "inactive"
    assert _classify_status("Liquidated") == "inactive"
    assert _classify_status("Приостановлено") == "inactive"
    assert _classify_status(None) is None


def test_parse_capital_handles_kgs_amounts():
    amount, currency = _parse_capital("100 000,00 сом")
    assert amount == 100000.0
    assert currency == "KGS"

    amount, currency = _parse_capital("5 000 000 KGS")
    assert amount == 5000000.0
    assert currency == "KGS"

    amount, currency = _parse_capital("1,500.50 USD")
    assert amount == 1500.50
    assert currency == "USD"

    amount, currency = _parse_capital("")
    assert amount is None
    assert currency is None


def test_extract_company_record_parses_two_column_table():
    html = """
    <html><body>
      <table>
        <tr><td>Полное наименование:</td><td>ОАО "Кыргызалтын"</td></tr>
        <tr><td>ИНН:</td><td>01410199810177</td></tr>
        <tr><td>Организационно-правовая форма:</td><td>Открытое акционерное общество</td></tr>
        <tr><td>Статус:</td><td>Действующее</td></tr>
        <tr><td>Юридический адрес:</td><td>г. Бишкек, пр. Чуй, 24</td></tr>
        <tr><td>Уставный капитал:</td><td>100 000 000,00 сом</td></tr>
        <tr><td>Дата регистрации:</td><td>22.06.1992</td></tr>
        <tr><td>ОКПО:</td><td>22996521</td></tr>
        <tr><td>Руководитель:</td><td>Иванов И.И.</td></tr>
      </table>
    </body></html>
    """
    record = _extract_company_record(html)
    assert "Кыргызалтын" in record["name"]
    assert record["legal_form"].startswith("Открытое")
    assert record["status_raw"] == "Действующее"
    assert "Бишкек" in record["address"]
    assert record["capital"] == "100 000 000,00 сом"
    assert record["registration_date"] == "22.06.1992"
    assert record["okpo"] == "22996521"
    assert "Иванов И.И." in record["directors"]


def test_extract_company_record_empty_when_no_table():
    assert _extract_company_record("") == {}
    assert _extract_company_record("<html><body>No data</body></html>") == {}


def test_extract_search_results_finds_anchor_matches():
    html = """
    <table>
      <tr><td><a href="/register/?inn=01410199810177">
        ОАО Кыргызалтын
      </a></td><td>Бишкек</td></tr>
      <tr><td><a href="/register/?inn=02401199810064">
        ЗАО KICB
      </a></td></tr>
    </table>
    """
    results = _extract_search_results(html)
    ids = [r["id"] for r in results]
    assert "01410199810177" in ids
    assert "02401199810064" in ids


def test_extract_search_results_handles_plain_text_fallback():
    html = """
    <table>
      <tr><td>ОАО Кыргызалтын</td><td>01410199810177</td></tr>
    </table>
    """
    results = _extract_search_results(html)
    assert results
    assert results[0]["id"] == "01410199810177"


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = KGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "01410199810177")


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty():
    adapter = KGAdapter()
    assert await adapter.fetch_financials("01410199810177") == []


@pytest.mark.asyncio
async def test_fetch_financials_validates_inn():
    adapter = KGAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-an-inn")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_status():
    adapter = KGAdapter()
    health = await adapter.health_check()
    assert health.country_code == "KG"
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_kyrgyzaltyn_returns_company_details():
    adapter = KGAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "01410199810177"
    )
    assert details is not None
    assert details.country == "KG"
    assert details.id == "01410199810177"
    assert details.name
    upper = details.name.upper()
    assert any(
        token in upper
        for token in ("КЫРГЫЗАЛТЫН", "KYRGYZALTYN")
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_kicb_returns_company_details():
    adapter = KGAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "02401199810064"
    )
    assert details is not None
    assert details.id == "02401199810064"
    upper = details.name.upper()
    assert any(token in upper for token in ("KICB", "КИКБ", "КЫРГЫЗ"))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_returns_matches():
    adapter = KGAdapter()
    results = await adapter.search_by_name("Кыргызалтын", limit=5)
    assert isinstance(results, list)
    if results:
        assert any(r.id == "01410199810177" for r in results)
