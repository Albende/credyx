"""Tests for the KR (OpenDART) adapter.

Unit tests exercise the parser without hitting the network. Integration
tests hit the real OpenDART API and require `KR_OPENDART_API_KEY`. The
integration tests are marked `integration` so CI can opt-out with
`-m "not integration"`.
"""
from __future__ import annotations

import os

import pytest

from packages.adapters.kr import KRAdapter
from packages.adapters.kr.adapter import _parse_fnltt_all_accounts
from packages.shared.models import IdentifierType

_SAMSUNG_CORP_CODE = "00126380"

_HAS_KEY = bool(os.getenv("KR_OPENDART_API_KEY"))
_REQUIRES_KEY = pytest.mark.skipif(
    not _HAS_KEY, reason="KR_OPENDART_API_KEY not set; OpenDART tests require a free key."
)


def _row(
    sj_div: str,
    account_nm: str,
    thstrm_amount: str,
    *,
    account_id: str = "",
    fs_div: str = "CFS",
    thstrm_dt: str = "제 55 기 (2023.12.31)",
    currency: str = "KRW",
) -> dict[str, str]:
    return {
        "sj_div": sj_div,
        "account_nm": account_nm,
        "account_id": account_id,
        "thstrm_amount": thstrm_amount,
        "fs_div": fs_div,
        "thstrm_dt": thstrm_dt,
        "currency": currency,
    }


def test_parse_fnltt_all_accounts_populates_every_section():
    items = [
        # Balance sheet
        _row("BS", "자산총계", "1,000,000,000"),
        _row("BS", "유동자산", "400,000,000"),
        _row("BS", "비유동자산", "600,000,000"),
        _row("BS", "현금및현금성자산", "50,000,000"),
        _row("BS", "재고자산", "30,000,000"),
        _row("BS", "매출채권", "20,000,000"),
        _row("BS", "부채총계", "600,000,000"),
        _row("BS", "유동부채", "200,000,000"),
        _row("BS", "비유동부채", "400,000,000"),
        _row("BS", "자본총계", "400,000,000"),
        _row("BS", "자본금", "100,000,000"),
        _row("BS", "이익잉여금", "250,000,000"),
        # Income statement
        _row("IS", "매출액", "800,000,000"),
        _row("IS", "매출총이익", "300,000,000"),
        _row("IS", "영업이익", "120,000,000"),
        _row("IS", "당기순이익", "90,000,000"),
        _row("IS", "감가상각비", "40,000,000"),
        _row("IS", "이자비용", "10,000,000"),
        # Cash flow
        _row("CF", "영업활동현금흐름", "150,000,000"),
        _row("CF", "투자활동현금흐름", "-90,000,000"),
        _row("CF", "재무활동현금흐름", "(20,000,000)"),
    ]
    structured, currency = _parse_fnltt_all_accounts(
        items, year=2023, consolidated=True
    )
    assert currency == "KRW"
    assert structured is not None
    assert structured["currency"] == "KRW"
    assert structured["period_end"] == "2023-12-31"
    assert structured["consolidated"] is True

    bs = structured["balance_sheet"]
    assert bs["total_assets"] == 1_000_000_000
    assert bs["current_assets"] == 400_000_000
    assert bs["non_current_assets"] == 600_000_000
    assert bs["cash_and_equivalents"] == 50_000_000
    assert bs["inventories"] == 30_000_000
    assert bs["trade_receivables"] == 20_000_000
    assert bs["total_liabilities"] == 600_000_000
    assert bs["current_liabilities"] == 200_000_000
    assert bs["non_current_liabilities"] == 400_000_000
    assert bs["total_equity"] == 400_000_000
    assert bs["share_capital"] == 100_000_000
    assert bs["retained_earnings"] == 250_000_000

    is_ = structured["income_statement"]
    assert is_["revenue"] == 800_000_000
    assert is_["gross_profit"] == 300_000_000
    assert is_["operating_profit"] == 120_000_000
    assert is_["net_income"] == 90_000_000
    assert is_["depreciation_amortization"] == 40_000_000
    assert is_["interest_expense"] == 10_000_000

    cf = structured["cash_flow"]
    assert cf["operating_cf"] == 150_000_000
    assert cf["investing_cf"] == -90_000_000
    assert cf["financing_cf"] == -20_000_000

    # raw_concepts should retain the original Korean labels.
    assert structured["raw_concepts"]["자산총계"] == 1_000_000_000
    assert structured["raw_concepts"]["매출액"] == 800_000_000


def test_parse_falls_back_to_concept_id_when_name_unknown():
    items = [
        # account_nm is non-standard but the K-IFRS concept_id is present.
        _row(
            "BS",
            "자산 합계",
            "500,000,000",
            account_id="ifrs-full_Assets",
        ),
        _row(
            "IS",
            "매출",
            "750,000,000",
            account_id="ifrs-full_Revenue",
        ),
    ]
    structured, _ = _parse_fnltt_all_accounts(items, year=2024, consolidated=True)
    assert structured is not None
    assert structured["balance_sheet"]["total_assets"] == 500_000_000
    assert structured["income_statement"]["revenue"] == 750_000_000


def test_parse_empty_returns_none():
    structured, currency = _parse_fnltt_all_accounts([], year=2023, consolidated=True)
    assert structured is None
    assert currency == "KRW"


def test_parse_marks_ofs_when_not_consolidated():
    items = [
        _row("BS", "자산총계", "100", fs_div="OFS"),
    ]
    structured, _ = _parse_fnltt_all_accounts(items, year=2023, consolidated=False)
    assert structured is not None
    assert structured["consolidated"] is False
    assert structured["balance_sheet"]["total_assets"] == 100.0


@pytest.mark.asyncio
@pytest.mark.integration
@_REQUIRES_KEY
async def test_search_finds_samsung():
    adapter = KRAdapter()
    matches = await adapter.search_by_name("Samsung Electronics", limit=10)
    assert matches, "expected at least one match for Samsung Electronics"
    assert any("samsung" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
@_REQUIRES_KEY
async def test_lookup_samsung_corp_code():
    adapter = KRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, _SAMSUNG_CORP_CODE
    )
    assert details is not None
    assert "samsung" in details.name.lower() or "삼성" in details.name
    assert details.country == "KR"
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == _SAMSUNG_CORP_CODE
        for i in details.identifiers
    )


@pytest.mark.asyncio
@pytest.mark.integration
@_REQUIRES_KEY
async def test_financials_samsung_have_structured_data():
    adapter = KRAdapter()
    filings = await adapter.fetch_financials(_SAMSUNG_CORP_CODE, years=3)
    assert filings, "expected at least one Samsung annual filing"
    with_structured = [f for f in filings if f.structured_data]
    assert with_structured, "expected at least one filing with structured_data"

    fy2023 = next((f for f in with_structured if f.year == 2023), with_structured[0])
    assert fy2023.currency == "KRW"
    data = fy2023.structured_data
    assert isinstance(data, dict)
    assert data.get("currency") == "KRW"
    assert isinstance(data.get("balance_sheet"), dict)
    assert isinstance(data.get("income_statement"), dict)
    assert isinstance(data.get("cash_flow"), dict)

    assert data["balance_sheet"].get("total_assets", 0) > 0
    assert data["income_statement"].get("revenue", 0) > 0
